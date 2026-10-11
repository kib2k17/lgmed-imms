from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core import media, pwa

urlpatterns = [
    # The Django admin has a sign-in form of its own, which knows nothing of
    # two-step verification. Sending it to the system's sign-in page (with its
    # ?next=) keeps a single way in, so there is no password-only side door.
    path(
        "django-admin/login/",
        RedirectView.as_view(pattern_name="accounts:login", query_string=True),
    ),
    path("django-admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),

    # Short alias for the login page.
    #
    # Nothing on the public site links to the login any more, so staff reach
    # the system by typing the address. "/staff" is what gets dictated over the
    # phone and bookmarked; "/accounts/login/" remains the canonical URL that
    # LOGIN_URL, the form action and every `?next=` redirect use. Both spellings
    # are registered so a missing trailing slash does not 404.
    path("staff", RedirectView.as_view(pattern_name="accounts:login")),
    path("staff/", RedirectView.as_view(pattern_name="accounts:login")),

    # Phase 2 modules.
    #
    # These are included at the project root rather than inside core.urls:
    # including a namespaced URLconf inside another one nests the namespaces
    # ("core:monitoring:list"), which no template expects.
    path("app/programs/", include("programs.urls")),
    path("app/monitoring/", include("monitoring.urls")),
    path("app/incoming/", include("incoming.urls")),
    path("app/outgoing/", include("outgoing.urls")),
    path("app/sync/", include("datasync.urls")),
    path("app/lgus/", include("lgus.urls")),
    path("app/services/", include("services.urls")),
    path("app/documents/", include("documents.urls")),
    path("app/announcements/", include("announcements.urls")),
    path("app/reports/", include("reports.urls")),
    path("app/calendar/", include("activities.urls")),
    path("app/updates/", include("updates.urls")),

    # Phase 3 administration
    path("app/settings/", include("administration.urls")),
    path("app/audit-logs/", include("audit.urls")),

    # Phase 4
    path("app/notifications/", include("notifications.urls")),
    path("app/analytics/", include("analytics.urls")),

    # LGMED Innovation Action
    path("app/esira/", include("esira.urls")),

    # Installable app (core/pwa.py). At the root, not under /static/ or /app/:
    # a service worker only controls the URLs below the one it was served
    # from, and the manifest and offline page are fetched without a sign-in.
    path("manifest.webmanifest", pwa.manifest, name="pwa_manifest"),
    path("sw.js", pwa.service_worker, name="pwa_service_worker"),
    path("offline/", pwa.offline, name="pwa_offline"),
    path("launch/", pwa.launch, name="pwa_launch"),

    # Uploaded files, in development and production alike. Never mapped by
    # the web server: every request is traced to its record and checked
    # (core/media.py), because MEDIA_ROOT holds internal papers as well as
    # what the public website shows.
    path(f"{settings.MEDIA_URL.strip('/')}/<path:path>", media.serve, name="media"),

    path("", include("core.urls")),
]

handler403 = "core.errors.permission_denied"
handler404 = "core.errors.page_not_found"
handler500 = "core.errors.server_error"
