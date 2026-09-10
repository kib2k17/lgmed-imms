"""
Institutional identity and navigation, available to every template.

All agency details are sourced from the LGMED-iMMS specification. Nothing here
is invented: if an official asset or detail is unavailable, the template falls
back to a neutral placeholder rather than fabricating one.

The identity is published as `agency`, not `site`. Django's own
`auth.views.LoginView` puts a `site` object into its context, and a view's
context beats a context processor - so under the name `site` every identity
value on the sign-in page silently rendered as empty string. Nothing errored;
the page just quietly lost its department name, system name and contact
address. `core/tests_templates.py` now guards the name.
"""

from pathlib import Path

from django.conf import settings

from .navigation import build_public_nav, build_sidebar

AGENCY = {
    "system_name": "LGMED-iMMS",
    "system_full_name": (
        "Local Government Monitoring and Evaluation Division - "
        "Information Management and Monitoring System"
    ),
    "department": "Department of the Interior and Local Government",
    "office": "Regional Office XIII - Caraga",
    "office_short": "DILG Region XIII - Caraga",
    "division": "Local Government Monitoring and Evaluation Division",
    "division_short": "LGMED",
    "address": "Purok 1-A, Brgy. Doongan, Butuan City, 8600",
    "telephone": "(085) 975-9830 to 34",
    "email": "RegionalOffice@caraga.dilg.gov.ph",
    "logo_static_path": "img/dilg-logo.png",
}


def _logo_is_available():
    """
    Whether the official seal has actually been supplied.

    Checked through the staticfiles finders rather than by guessing a path, so
    it works the same in development and behind collectstatic. Cached outside
    DEBUG because it is read on every page and the answer cannot change while
    the process is running.
    """
    from django.contrib.staticfiles import finders

    return bool(finders.find(AGENCY["logo_static_path"]))


_LOGO_AVAILABLE = None


def site_identity(request):
    """
    The agency's identity, with the details an officer maintains laid over it.

    `AGENCY` above is the fallback, not the source of truth: address,
    telephone and email are editable on the Public Website page, so a move or
    a new trunk line is an edit rather than a deployment. Everything else -
    the department, the office, the division - is the office's legal identity
    and is not editable from inside the system.
    """
    global _LOGO_AVAILABLE

    if settings.DEBUG or _LOGO_AVAILABLE is None:
        _LOGO_AVAILABLE = _logo_is_available()

    from administration.models import PublicSiteContent

    content = PublicSiteContent.load()

    return {
        "agency": {
            **AGENCY,
            "address": content.address,
            "telephone": content.telephone,
            "telephone_link": content.telephone_link,
            "email": content.email,
            "office_hours": content.office_hours,
            "facebook_url": content.facebook_url,
            "has_logo": _LOGO_AVAILABLE,
        },
        "public_content": content,
        "debug": settings.DEBUG,
    }


def navigation(request):
    user = getattr(request, "user", None)
    path = request.path

    return {
        "sidebar_sections": build_sidebar(
            user,
            resolver_match=getattr(request, "resolver_match", None),
            current_path=path,
        ),
        "public_nav": build_public_nav(current_path=path),
    }


def system_settings(request):
    """
    System-wide preferences, available to every template.

    Read from a cached singleton, so the extra query happens once every five
    minutes rather than on every page.
    """
    from administration.models import SystemSetting

    return {"system_settings": SystemSetting.load()}


def notifications(request):
    """
    The signed-in user's unread notifications, for the header bell.

    Capped at five for the dropdown: the bell is a prompt to look, not the
    place to work through a backlog - the full list is a page of its own.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"unread_notifications": 0, "recent_notifications": []}

    from notifications.models import Notification

    unread = Notification.objects.for_user(user).unread()
    return {
        "unread_notifications": unread.count(),
        "recent_notifications": list(unread[:5]),
    }


def asset_version(request):
    """
    A cache-busting stamp for the stylesheet and the script, in development.

    `app.css` is compiled by hand with `build-css.ps1`, so during development
    the browser holds a copy from before the last build and every new utility
    class silently does nothing: a hover state that never hides, a wrap that
    never wraps, a swatch that never appears. Nothing errors, and the page
    looks like the change was never made - which costs more time to diagnose
    than a stat call costs to serve.

    In production `ManifestStaticFilesStorage` already puts a content hash in
    the filename, so the stamp is empty and the URL is left alone.
    """
    if not settings.DEBUG:
        return {"asset_version": ""}

    newest = 0
    for name in ("css/app.css", "js/app.js"):
        for root in [settings.STATIC_ROOT, *settings.STATICFILES_DIRS]:
            if not root:
                continue
            path = Path(root) / name
            try:
                newest = max(newest, int(path.stat().st_mtime))
            except OSError:
                continue
    return {"asset_version": str(newest)}
