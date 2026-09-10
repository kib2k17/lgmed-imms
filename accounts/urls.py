from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    # Authentication
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),

    # Users & Roles (administrators only - the views enforce it)
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/new/", views.UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path("users/<int:pk>/edit/", views.UserUpdateView.as_view(), name="user_update"),
    path("users/<int:pk>/password/", views.UserPasswordResetView.as_view(),
         name="user_password"),
    path("users/<int:pk>/activation/", views.UserActivationView.as_view(),
         name="user_activation"),
    path("roles/", views.RoleListView.as_view(), name="role_list"),
]
