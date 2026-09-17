from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Public website
    path("", views.home, name="home"),
    path("about/", views.public_about, name="public_about"),
    path("programs/", views.public_programs, name="public_programs"),
    # Programmes are addressed by slug, never by database number: a public URL
    # that counts upward tells a visitor how many records exist and lets them
    # walk the ones that do not.
    path("programs/outcome/<slug:slug>/", views.public_outcome, name="public_outcome"),
    path("programs/program/<slug:slug>/", views.public_program, name="public_program"),
    path("programs/project/<slug:slug>/", views.public_project, name="public_project"),
    path("programs/sub-project/<slug:slug>/", views.public_subproject,
         name="public_subproject"),
    path("programs/activity/<slug:slug>/", views.public_activity,
         name="public_activity"),
    path("programs/file/<uuid:token>/", views.public_document_file,
         name="public_document_file"),
    path("services/", views.public_services, name="public_services"),
    path("announcements/", views.public_announcements, name="public_announcements"),
    path("announcements/<slug:slug>/", views.public_announcement, name="public_announcement"),
    path("accomplishments/", views.public_updates, name="public_updates"),
    path("accomplishments/<int:pk>/", views.public_update_week, name="public_update_week"),
    path("statistics/", views.public_statistics, name="public_statistics"),
    path("reports/", views.public_reports, name="public_reports"),
    path("documents/", views.public_documents, name="public_documents"),
    path("calendar/", views.public_calendar, name="public_calendar"),
    path("contact/", views.public_contact, name="public_contact"),

    # Internal system
    path("app/", views.dashboard, name="dashboard"),
    path("app/design-system/", views.components, name="components"),
]
