from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),

    # Phase 2 modules.
    #
    # These are included at the project root rather than inside core.urls:
    # including a namespaced URLconf inside another one nests the namespaces
    # ("core:monitoring:list"), which no template expects.
    path("app/programs/", include("programs.urls")),
    path("app/monitoring/", include("monitoring.urls")),
    path("app/incoming/", include("incoming.urls")),
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

    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "core.errors.permission_denied"
handler404 = "core.errors.page_not_found"
handler500 = "core.errors.server_error"
