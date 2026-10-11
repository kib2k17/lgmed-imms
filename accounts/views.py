from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.generic import FormView, TemplateView

from audit.models import Action, AuditEvent
from audit.recording import record
from core.mixins import CanAdministerMixin, CapabilityRequiredMixin
from core.views_base import (
    ModuleCreateView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)

from core.context_processors import AGENCY

from . import menu_access, mfa, photos, privacy, recaptcha, totp
from .capabilities import CAPABILITIES, role_matrix
from .emails import send_account_created_notice, send_welcome_email
from .forms import (
    AdminSetPasswordForm,
    LoginForm,
    MFACodeForm,
    ProfilePhotoForm,
    UserCreateForm,
    UserForm,
)
from .models import Role, User


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Only the public half of the pair ever reaches a template. Empty when
        # reCAPTCHA is not configured, which is what the page tests to decide
        # whether to load Google's script at all.
        context["recaptcha_site_key"] = (
            settings.RECAPTCHA_SITE_KEY if recaptcha.is_enabled() else ""
        )
        context["recaptcha_action"] = recaptcha.LOGIN_ACTION
        return context

    def get(self, request, *args, **kwargs):
        # Coming back to the sign-in page abandons any sign-in left halfway,
        # so "use another account" is simply a link here.
        mfa.clear(request)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()

        # The password was right, but it is only the first step for anyone
        # with an authenticator app - and for an administrator without one,
        # who must enrol before going any further.
        # (Skipped while LGMED_MFA_OFF is set, in development only.)
        if not settings.MFA_OFF and (user.mfa_enabled or user.mfa_required):
            mfa.begin(self.request, user, self.get_success_url())
            if user.mfa_enabled:
                return redirect("accounts:mfa_verify")
            return redirect("accounts:mfa_setup")

        response = super().form_valid(form)
        messages.success(
            self.request, f"Signed in as {self.request.user.get_display_name()}."
        )
        return response


class LogoutView(auth_views.LogoutView):
    # No next_page: LOGOUT_REDIRECT_URL decides where signing out lands, and it
    # points at the login page. Hard-coding it here silently overrode the
    # setting.
    pass


@login_required
def profile(request, photo_form=None):
    # The code field sits halfway down the page; it must not grab the focus.
    mfa_form = MFACodeForm(dense=True)
    mfa_form.fields["code"].widget.attrs.pop("autofocus", None)
    context = {
        "page_title": "My Profile",
        "page_subtitle": "Account details and system access",
        "breadcrumbs": [{"label": "My Profile"}],
        "active_nav": "profile",
        "capabilities": CAPABILITIES,
        "recent_events": (
            AuditEvent.objects.filter(actor=request.user)[:10]
        ),
        "mfa_recovery_left": (
            mfa.recovery_codes_left(request.user)
            if request.user.mfa_enabled else 0
        ),
        "mfa_form": mfa_form,
        "photo_form": photo_form or ProfilePhotoForm(),
    }
    return render(request, "accounts/profile.html", context)


@login_required
@require_POST
def profile_photo_upload(request):
    form = ProfilePhotoForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "The profile photo was not changed.")
        return profile(request, photo_form=form)
    photos.replace_photo(request.user, form.processed)
    messages.success(request, "Your profile photo has been updated.")
    return redirect("accounts:profile")


@login_required
@require_POST
def profile_photo_remove(request):
    photos.remove_photo(request.user)
    messages.success(request, "Your profile photo has been removed.")
    return redirect("accounts:profile")


@login_required
def user_photo(request, pk):
    """
    Serve an account's profile photo to anyone signed in.

    Colleagues see each other's photos in the user list and the top bar, so
    any session may read one; the public, and search engines, may not - the
    file sits in the protected root and this view is the only way to it.
    """
    account = get_object_or_404(User, pk=pk)
    if not account.photo:
        raise Http404("This account has no profile photo.")
    try:
        handle = account.photo.open("rb")
    except FileNotFoundError:
        raise Http404("The photo is missing from storage.")
    response = FileResponse(handle, content_type="image/jpeg")
    # The URL carries a version that changes with every upload, so the
    # browser may keep it - but only its own copy, never a shared cache.
    response["Cache-Control"] = "private, max-age=86400"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
@require_POST
def privacy_notice_accept(request):
    """
    Records that the signed-in user has read the Data Privacy Act notice.

    The checkbox is required in the browser too, but the server does not take
    that on trust: an acknowledgement without it is not an acknowledgement.
    """
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = settings.LOGIN_REDIRECT_URL

    if not request.POST.get("agree"):
        messages.error(
            request,
            "Please tick the box to confirm that you have read the privacy "
            "notice before continuing.",
        )
        return redirect(next_url)

    if privacy.is_pending(request):
        privacy.acknowledge(request)
        record(
            Action.PRIVACY_ACKNOWLEDGED, actor=request.user, request=request,
            detail="Read and agreed to the Data Privacy Act (RA 10173) notice",
        )
    return redirect(next_url)


# ---------------------------------------------------------------------------
# Two-step verification
# ---------------------------------------------------------------------------


def _signin_expired(request):
    messages.info(
        request,
        "Your sign-in was not completed in time. Please enter your password again.",
    )
    return redirect("accounts:login")


@method_decorator(never_cache, name="dispatch")
class MFAVerifyView(FormView):
    """The second step of signing in: the code from the authenticator app."""

    template_name = "registration/mfa_verify.html"
    form_class = MFACodeForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        self.account = mfa.pending_user(request)
        if self.account is None:
            return _signin_expired(request)
        if not self.account.mfa_enabled:
            return redirect("accounts:mfa_setup")
        self.recovery = (request.GET.get("recovery") or request.POST.get("recovery")) == "1"
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["recovery"] = self.recovery
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "account": self.account,
            "recovery": self.recovery,
            "locked": mfa.is_locked(self.account.mfa_device),
        })
        return context

    def form_valid(self, form):
        request = self.request
        account = self.account
        outcome = mfa.check(account, form.cleaned_data["code"])

        if outcome.ok:
            redirect_to = mfa.complete(request, account)
            messages.success(request, f"Signed in as {account.get_display_name()}.")
            if outcome.method == "recovery":
                record(
                    Action.MFA_RECOVERY_USED, actor=account, target=account,
                    detail=f"Signed in with a recovery code "
                           f"({outcome.recovery_left} left)",
                )
                messages.warning(
                    request,
                    f"You signed in with a recovery code. You have "
                    f"{outcome.recovery_left} left. If your phone is lost, turn "
                    "two-step verification off and set it up again on a new one.",
                )
            return redirect(redirect_to or settings.LOGIN_REDIRECT_URL)

        record(
            Action.LOGIN_FAILED, request=request, target=account,
            detail=f"Wrong two-step verification code for '{account.username}'",
        )
        if outcome.locked:
            mfa.clear(request)
            messages.error(
                request,
                "Too many wrong codes. Two-step verification for this account is "
                f"locked for {int(mfa.LOCKOUT_DURATION.total_seconds() // 60)} "
                "minutes. If this was not you, contact the system administrator.",
            )
            return redirect("accounts:login")
        if not mfa.count_failure(request):
            messages.error(request, "Too many wrong codes. Please sign in again.")
            return redirect("accounts:login")

        form.add_error(
            "code",
            "That recovery code is not valid or has already been used."
            if self.recovery else
            "That code is not correct. Enter the code your authenticator app "
            "is showing now.",
        )
        return self.form_invalid(form)


@method_decorator(never_cache, name="dispatch")
class MFASetupView(FormView):
    """
    Enrol an authenticator app.

    Reached two ways: from My Profile by anyone signed in, and in the middle
    of signing in by an administrator who has not enrolled yet - who is not
    signed in until the phone has been proved.
    """

    form_class = MFACodeForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.account = request.user
            self.during_signin = False
            if self.account.mfa_enabled:
                messages.info(request, "Two-step verification is already on.")
                return redirect("accounts:profile")
        else:
            self.account = mfa.pending_user(request)
            if self.account is None:
                return _signin_expired(request)
            # Someone holding only the password must never be able to enrol
            # a phone of their own in place of the real one.
            if self.account.mfa_enabled:
                return redirect("accounts:mfa_verify")
            self.during_signin = True
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        if self.during_signin:
            return ["registration/mfa_setup.html"]
        return ["accounts/mfa_setup.html"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["dense"] = not self.during_signin
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        secret = mfa.setup_secret(self.request, self.account)
        uri = totp.provisioning_uri(
            secret, account=self.account.username, issuer=AGENCY["system_name"],
        )
        context.update({
            "account": self.account,
            "during_signin": self.during_signin,
            "qr_svg": mark_safe(totp.qr_svg(uri)),
            "secret_grouped": totp.group(secret),
            "page_title": "Set Up Two-Step Verification",
            "page_subtitle": "Protect your account with an authenticator app",
            "active_nav": "profile",
            "breadcrumbs": [
                {"label": "My Profile", "url": reverse("accounts:profile")},
                {"label": "Two-step verification"},
            ],
        })
        return context

    def form_valid(self, form):
        request = self.request
        account = self.account
        secret = mfa.setup_secret(request, account)
        step = totp.match(secret, form.cleaned_data["code"])
        if step is None:
            form.add_error(
                "code",
                "That code does not match. Make sure the time on your phone is "
                "set automatically, then enter the code the app is showing now.",
            )
            return self.form_invalid(form)

        codes = mfa.enrol(account, secret, step)
        request.session.pop(mfa.SETUP_KEY, None)

        if self.during_signin:
            next_url = mfa.complete(request, account)
            messages.success(request, f"Signed in as {account.get_display_name()}.")
        else:
            next_url = reverse("accounts:profile")
        record(
            Action.MFA_ENABLED, actor=account, target=account,
            detail="Authenticator app enrolled",
        )
        mfa.hold_fresh_codes(request, codes, next_url)
        return redirect("accounts:mfa_recovery_codes")


@never_cache
@login_required
def mfa_recovery_codes(request):
    """Show newly issued recovery codes - once."""
    fresh = mfa.take_fresh_codes(request)
    if not fresh:
        return redirect("accounts:profile")
    return render(request, "accounts/mfa_recovery_codes.html", {
        "codes": fresh["codes"],
        "next_url": fresh["next"] or reverse("accounts:profile"),
        "page_title": "Recovery Codes",
        "page_subtitle": "Save these now - they will not be shown again",
        "active_nav": "profile",
        "breadcrumbs": [
            {"label": "My Profile", "url": reverse("accounts:profile")},
            {"label": "Recovery codes"},
        ],
    })


def _confirm_with_code(request):
    """
    Check the code posted with a sensitive change to the account's own two-step
    verification. A signed-in session alone is not enough to switch it off:
    that session may be a laptop left unlocked.
    """
    form = MFACodeForm(request.POST, dense=True)
    if not form.is_valid():
        messages.error(request, "Enter a code from your authenticator app.")
        return False
    outcome = mfa.check(request.user, form.cleaned_data["code"])
    if outcome.ok:
        return True
    if outcome.locked:
        messages.error(
            request,
            "Too many wrong codes. Two-step verification is locked for "
            f"{int(mfa.LOCKOUT_DURATION.total_seconds() // 60)} minutes.",
        )
    else:
        messages.error(request, "That code is not correct. Nothing was changed.")
    return False


@require_POST
@login_required
def mfa_disable(request):
    user = request.user
    if not user.mfa_enabled:
        return redirect("accounts:profile")
    if not _confirm_with_code(request):
        return redirect("accounts:profile")

    mfa.disable(user)
    record(
        Action.MFA_DISABLED, target=user,
        detail="Turned off by the account holder",
    )
    if user.mfa_required:
        messages.info(
            request,
            "Your old authenticator was removed. Your role requires two-step "
            "verification, so set it up on your new phone now.",
        )
        return redirect("accounts:mfa_setup")
    messages.success(request, "Two-step verification is off for your account.")
    return redirect("accounts:profile")


@require_POST
@login_required
def mfa_regenerate_codes(request):
    user = request.user
    if not user.mfa_enabled:
        return redirect("accounts:profile")
    if not _confirm_with_code(request):
        return redirect("accounts:profile")

    codes = mfa.issue_recovery_codes(user)
    record(
        Action.MFA_CODES_RENEWED, target=user,
        detail="New recovery codes issued; the old ones no longer work",
    )
    mfa.hold_fresh_codes(request, codes, reverse("accounts:profile"))
    return redirect("accounts:mfa_recovery_codes")


# ---------------------------------------------------------------------------
# Users & Roles (administrators only)
# ---------------------------------------------------------------------------


def _refuse_if_outranked(request, account):
    """
    An Administrator manages accounts, but not the System Administrator's.

    Resetting a System Administrator's password and two-step verification is
    a takeover of the account in two clicks; editing it, or deactivating it,
    is the same thing done more slowly. Only another System Administrator may.
    """
    if account.is_superadmin and not request.user.is_superadmin:
        raise PermissionDenied(
            "Only a System Administrator can change a System Administrator's account."
        )


class UserModuleMixin(CanAdministerMixin):
    model = User
    module_key = "users"
    module_label = "User Account"
    list_label = "Users & Roles"
    module_url_name = "accounts:user_list"


class UserListView(UserModuleMixin, ModuleListView):
    page_title = "Users & Roles"
    page_subtitle = "System accounts and the access each one carries"
    module_label = "User Accounts"
    template_name = "dashboard/users/list.html"
    search_placeholder = "Search name, username, position..."
    search_fields = ("username", "first_name", "last_name", "email", "position")
    sort_fields = ("username", "last_name", "role", "is_active", "last_login")
    default_sort = "last_name"
    create_url_name = "accounts:user_create"
    create_label = "Add Account"
    empty_icon = "users"
    filter_fields = (
        ("role", "Role", Role.choices),
        ("is_active", "Status", [("True", "Active"), ("False", "Deactivated")]),
    )
    export_columns = (
        ("Username", "username"),
        ("Name", "get_display_name"),
        ("Position", "position"),
        ("Office", "office"),
        ("Email", "email"),
        ("Role", "get_role_display"),
        ("Active", "is_active"),
        ("Last sign-in", "last_login"),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accounts = User.objects.all()
        context["summary"] = accounts.aggregate(
            total=Count("pk"),
            active=Count("pk", filter=Q(is_active=True)),
            administrators=Count(
                "pk", filter=Q(role__in=(Role.SUPERADMIN, Role.ADMIN))
            ),
            deactivated=Count("pk", filter=Q(is_active=False)),
        )
        return context


class UserDetailView(UserModuleMixin, ModuleDetailView):
    template_name = "dashboard/users/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        account = self.object
        context["page_title"] = account.get_display_name()
        context["page_subtitle"] = (
            f"{account.position or account.get_role_display()} - {account.username}"
        )
        context["capabilities"] = CAPABILITIES
        context["recent_events"] = AuditEvent.objects.filter(actor=account)[:15]
        context["is_self"] = account.pk == self.request.user.pk
        context["mfa_recovery_left"] = (
            mfa.recovery_codes_left(account) if account.mfa_enabled else 0
        )
        return context


class UserCreateView(UserModuleMixin, ModuleCreateView):
    form_class = UserCreateForm
    module_label = "User Account"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Saving waits on the welcome email, which can take several seconds.
        context["loading_title"] = "Creating the account…"
        context["loading_note"] = (
            "Saving the account and sending the welcome email. "
            "Please keep this page open."
        )
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["acting_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        if send_welcome_email(self.object, form.temporary_password, self.request):
            messages.success(
                self.request,
                "A welcome email with the username, role and a temporary "
                f"password was sent to {self.object.email}.",
            )
        else:
            messages.warning(
                self.request,
                f"The account was created, but the welcome email to "
                f"{self.object.email} could not be sent. Use Reset password "
                f"to set a new one and give it to "
                f"{self.object.get_display_name()} by a separate channel.",
            )
        send_account_created_notice(self.object, self.request.user, self.request)
        return response


class UserUpdateView(UserModuleMixin, ModuleUpdateView):
    form_class = UserForm

    def get_object(self, queryset=None):
        account = super().get_object(queryset)
        _refuse_if_outranked(self.request, account)
        return account

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["acting_user"] = self.request.user
        return kwargs


class UserPasswordResetView(CanAdministerMixin, FormView):
    """Set a new password for another account."""

    template_name = "dashboard/users/password.html"
    form_class = AdminSetPasswordForm

    def dispatch(self, request, *args, **kwargs):
        self.account = get_object_or_404(User, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.account
        return kwargs

    def get(self, request, *args, **kwargs):
        _refuse_if_outranked(request, self.account)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        _refuse_if_outranked(request, self.account)
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "account": self.account,
                "active_nav": "users",
                "page_title": "Reset Password",
                "page_subtitle": self.account.get_display_name(),
                "breadcrumbs": [
                    {"label": "Users & Roles", "url": reverse("accounts:user_list")},
                    {
                        "label": self.account.get_display_name(),
                        "url": self.account.get_absolute_url(),
                    },
                    {"label": "Reset password"},
                ],
            }
        )
        return context

    def form_valid(self, form):
        form.save()
        record(
            Action.PASSWORD_RESET,
            target=self.account,
            detail=(
                f"Password reset by {self.request.user.get_display_name()}"
            ),
        )
        messages.success(
            self.request,
            f"The password for {self.account.get_display_name()} was reset. "
            "Pass it on securely and ask them to change it at first sign-in.",
        )
        return redirect(self.account.get_absolute_url())


class UserActivationView(CanAdministerMixin, FormView):
    """
    Deactivate or reactivate an account.

    Accounts are never deleted: their history has to remain attributable in
    the audit trail. Deactivating stops sign-in and leaves the record intact.
    """

    http_method_names = ["post"]

    def post(self, request, pk):
        account = get_object_or_404(User, pk=pk)
        if account.pk == request.user.pk:
            raise PermissionDenied("You cannot deactivate your own account.")
        _refuse_if_outranked(request, account)

        account.is_active = not account.is_active
        account.save(update_fields=["is_active"])  # the signal records it

        messages.success(
            request,
            f"{account.get_display_name()} was "
            f"{'reactivated' if account.is_active else 'deactivated'}.",
        )
        return redirect(account.get_absolute_url())


class UserMFAResetView(CanAdministerMixin, FormView):
    """
    Remove another account's authenticator, for a lost or replaced phone.

    The holder sets it up again at their next sign-in (administrators must;
    everyone else may). Resetting your own is done from My Profile, where it
    needs a code - here it would let a session left open switch it off.
    """

    http_method_names = ["post"]

    def post(self, request, pk):
        account = get_object_or_404(User, pk=pk)
        if account.pk == request.user.pk:
            raise PermissionDenied(
                "Manage your own two-step verification from My Profile."
            )
        _refuse_if_outranked(request, account)
        if account.mfa_enabled:
            mfa.disable(account)
            record(
                Action.MFA_DISABLED, target=account,
                detail=f"Reset by {request.user.get_display_name()}",
            )
            messages.success(
                request,
                f"Two-step verification was reset for {account.get_display_name()}. "
                + (
                    "They will be asked to set it up again at their next sign-in."
                    if account.mfa_required else
                    "They can set it up again from My Profile."
                ),
            )
        return redirect(account.get_absolute_url())


class RoleListView(CanAdministerMixin, ModuleListView):
    """
    The role matrix: what each role may do, and who holds it.

    Roles are defined in code rather than edited at runtime, because they gate
    server-side permission checks. This page documents them and links through
    to the accounts holding each one.
    """

    model = User
    module_key = "roles"
    module_label = "Roles"
    list_label = "Roles & Permissions"
    module_url_name = "accounts:role_list"
    page_title = "Roles & Permissions"
    page_subtitle = "What each role may do, and who currently holds it"
    template_name = "dashboard/roles/list.html"
    paginate_by = None
    exportable = False

    def get_base_queryset(self):
        return User.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["capabilities"] = CAPABILITIES
        context["roles"] = role_matrix()
        return context


# ---------------------------------------------------------------------------
# Menu Permissions
# ---------------------------------------------------------------------------


class SuperadminRequiredMixin(CapabilityRequiredMixin):
    """The System Administrator only - not every Administrator."""

    capability = "is_superadmin"


class MenuPermissionsView(SuperadminRequiredMixin, TemplateView):
    """
    Which sidebar modules each role is offered, and the accounts that differ.

    A tick opens a module to a role; clearing it removes the module from the
    sidebar of every account holding the role and refuses its URLs. A module
    the role's capabilities do not cover has no tick to give.
    """

    template_name = "dashboard/roles/menu_permissions.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        overridden = (
            User.objects.filter(module_access__isnull=False)
            .annotate(rules=Count("module_access"))
            .order_by("last_name", "first_name", "username")
        )
        context.update({
            "active_nav": "menu_permissions",
            "page_title": "Menu Permissions",
            "page_subtitle": "Which modules each role and account is offered",
            "breadcrumbs": [
                {"label": "Users & Roles", "url": reverse("accounts:user_list")},
                {"label": "Menu Permissions"},
            ],
            "roles": menu_access.managed_roles(),
            "rows": menu_access.role_matrix(),
            "overridden": overridden,
            "accounts": User.objects.filter(is_active=True)
            .exclude(is_superuser=True).exclude(role=Role.SUPERADMIN)
            .order_by("last_name", "first_name", "username"),
        })
        return context

    def post(self, request, *args, **kwargs):
        enabled = set()
        for value in request.POST.getlist("access"):
            module, _, role = value.partition(":")
            enabled.add((module, role))
        changes = menu_access.save_role_matrix(enabled, request.user)
        if changes:
            record(
                Action.UPDATE,
                request=request,
                target_label="Menu permissions by role",
                detail="; ".join(changes),
            )
            messages.success(
                request,
                f"Menu permissions saved: {len(changes)} change"
                f"{'s' if len(changes) != 1 else ''}.",
            )
        else:
            messages.info(request, "No menu permissions were changed.")
        return redirect("accounts:menu_permissions")


class UserMenuPermissionsView(SuperadminRequiredMixin, TemplateView):
    """One account's modules: follow the role, or open or close each one."""

    template_name = "dashboard/users/menu_permissions.html"

    def dispatch(self, request, *args, **kwargs):
        self.account = get_object_or_404(User, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        account = self.account
        context.update({
            "active_nav": "menu_permissions",
            "page_title": f"Menu Permissions: {account.get_display_name()}",
            "page_subtitle": f"{account.get_role_label()} - {account.username}",
            "breadcrumbs": [
                {"label": "Users & Roles", "url": reverse("accounts:user_list")},
                {"label": "Menu Permissions",
                 "url": reverse("accounts:menu_permissions")},
                {"label": account.get_display_name()},
            ],
            "account": account,
            "exempt": menu_access.is_exempt(account),
            "rows": [] if menu_access.is_exempt(account)
            else menu_access.user_matrix(account),
        })
        return context

    def post(self, request, *args, **kwargs):
        account = self.account
        if menu_access.is_exempt(account):
            raise PermissionDenied(
                "The System Administrator always has every module."
            )
        choices = {
            key: request.POST.get(f"module_{key}", menu_access.INHERIT)
            for key in menu_access.MANAGED_MODULES
        }
        changes = menu_access.save_user_matrix(account, choices, request.user)
        if changes:
            record(
                Action.UPDATE,
                request=request,
                target=account,
                detail="Menu permissions: " + "; ".join(changes),
            )
            messages.success(
                request,
                f"Menu permissions for {account.get_display_name()} saved.",
            )
        else:
            messages.info(request, "No menu permissions were changed.")
        return redirect("accounts:user_menu_permissions", pk=account.pk)
