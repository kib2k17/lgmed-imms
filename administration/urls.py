from django.urls import path

from . import views

app_name = "administration"

urlpatterns = [
    path("", views.SettingsView.as_view(), name="settings"),
    path("public-site/", views.PublicSiteView.as_view(), name="public_site"),
    path("reference/<slug:slug>/new/", views.reference_form, name="reference_create"),
    path("reference/<slug:slug>/<int:pk>/edit/", views.reference_form,
         name="reference_update"),
    path("reference/<slug:slug>/<int:pk>/delete/", views.reference_delete,
         name="reference_delete"),
]
