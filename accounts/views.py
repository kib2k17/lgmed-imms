from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import FormView

from audit.models import Action, AuditEvent
from audit.recording import record
from core.mixins import CanAdministerMixin
from core.views_base import (
    ModuleCreateView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)

from . import recaptcha
from .capabilities import CAPABILITIES, role_matrix
from .forms import AdminSetPasswordForm, LoginForm, UserCreateForm, UserForm
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

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request, f"Signed in as {self.request.user.get_display_name()}."
        )
        return response


class LogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("core:home")


@login_required
def profile(request):
    context = {
        "page_title": "My Profile",
        "page_subtitle": "Account details and system access",
        "breadcrumbs": [{"label": "My Profile"}],
        "active_nav": "profile",
        "capabilities": CAPABILITIES,
        "recent_events": (
            AuditEvent.objects.filter(actor=request.user)[:10]
        ),
    }
    return render(request, "accounts/profile.html", context)


# ---------------------------------------------------------------------------
# Users & Roles (administrators only)
# ---------------------------------------------------------------------------


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
        return context


class UserCreateView(UserModuleMixin, ModuleCreateView):
    form_class = UserCreateForm
    module_label = "User Account"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["acting_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.info(
            self.request,
            f"Give {self.object.get_display_name()} their temporary password "
            "in person or by a separate channel, and ask them to change it.",
        )
        return response


class UserUpdateView(UserModuleMixin, ModuleUpdateView):
    form_class = UserForm

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

        account.is_active = not account.is_active
        account.save(update_fields=["is_active"])  # the signal records it

        messages.success(
            request,
            f"{account.get_display_name()} was "
            f"{'reactivated' if account.is_active else 'deactivated'}.",
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
