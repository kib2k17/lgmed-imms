"""
Refuses the URLs of a module the System Administrator has closed.

The sidebar leaves a closed module out; this is what stops the address being
typed instead. It runs on the resolved view, so every URL of a module is
covered - its list, its records, its downloads - by the same lookup that lights
up the module's sidebar entry.
"""

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from audit.models import Action
from audit.recording import record

from .menu_access import can_access_module, module_for, nav_items


class ModuleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None

        key = module_for(getattr(request, "resolver_match", None))
        if key is None or can_access_module(user, key):
            return None

        # The dashboard is where signing in lands. Refusing it would greet an
        # account with an error page, so send it to the first module it does
        # have instead.
        if key == "dashboard":
            from core.navigation import build_sidebar

            for section in build_sidebar(user):
                if section["items"]:
                    return redirect(section["items"][0]["url"])

        label = next(
            (item["label"] for item in nav_items() if item["key"] == key), key
        )
        # Raised before the view runs, so AuditMiddleware.process_exception
        # never sees it; recorded here instead.
        record(
            Action.ACCESS_DENIED,
            request=request,
            detail=f"Access refused to {request.path}: {label} is closed to this account",
        )
        raise PermissionDenied(
            f"{label} is not enabled for your account. Ask the System "
            "Administrator if you need it."
        )


class PasswordChangeRequiredMiddleware:
    """
    Holds an account with a temporary password on the change-password page.

    A temporary password has been seen by someone other than its holder - in
    an email, or by the administrator who reset it. Until the holder replaces
    it, the account reaches nothing but the page that does so and what that
    page and signing in need on the way.
    """

    ALLOWED_VIEWS = {
        "accounts:password_change",
        "accounts:logout",
        # Signing in may pass through enrolling an authenticator first.
        "accounts:mfa_setup",
        "accounts:mfa_recovery_codes",
        "accounts:privacy_notice_accept",
        "accounts:user_photo",
        # The installable app's shell, fetched without regard to the page.
        "pwa_manifest",
        "pwa_service_worker",
        "pwa_offline",
        "pwa_launch",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.must_change_password:
            return None
        match = getattr(request, "resolver_match", None)
        if match is not None and match.view_name in self.ALLOWED_VIEWS:
            return None

        wants_page = (
            request.method in ("GET", "HEAD")
            and "text/html" in request.headers.get("Accept", "text/html")
        )
        if not wants_page:
            # A background request - the notification check, a save from a
            # page opened before - is refused rather than sent to a form.
            return JsonResponse(
                {"error": "Choose a new password before continuing."}, status=403
            )
        target = reverse("accounts:password_change")
        return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
