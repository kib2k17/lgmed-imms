from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    # Authentication
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("profile/photo/", views.profile_photo_upload, name="profile_photo"),
    path("profile/photo/remove/", views.profile_photo_remove,
         name="profile_photo_remove"),
    path("users/<int:pk>/photo/", views.user_photo, name="user_photo"),
    path("privacy-notice/accept/", views.privacy_notice_accept,
         name="privacy_notice_accept"),

    # Two-step verification
    path("login/verify/", views.MFAVerifyView.as_view(), name="mfa_verify"),
    path("mfa/setup/", views.MFASetupView.as_view(), name="mfa_setup"),
    path("mfa/recovery-codes/", views.mfa_recovery_codes,
         name="mfa_recovery_codes"),
    path("mfa/recovery-codes/renew/", views.mfa_regenerate_codes,
         name="mfa_regenerate_codes"),
    path("mfa/disable/", views.mfa_disable, name="mfa_disable"),

    # Users & Roles (administrators only - the views enforce it)
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/new/", views.UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path("users/<int:pk>/edit/", views.UserUpdateView.as_view(), name="user_update"),
    path("users/<int:pk>/password/", views.UserPasswordResetView.as_view(),
         name="user_password"),
    path("users/<int:pk>/activation/", views.UserActivationView.as_view(),
         name="user_activation"),
    path("users/<int:pk>/mfa-reset/", views.UserMFAResetView.as_view(),
         name="user_mfa_reset"),
    path("roles/", views.RoleListView.as_view(), name="role_list"),

    # Menu Permissions (System Administrator only)
    path("menu-permissions/", views.MenuPermissionsView.as_view(),
         name="menu_permissions"),
    path("users/<int:pk>/menu-permissions/",
         views.UserMenuPermissionsView.as_view(),
         name="user_menu_permissions"),
]
