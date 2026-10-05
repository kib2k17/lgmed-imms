from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.DocumentListView.as_view(), name="list"),
    path("new/", views.DocumentCreateView.as_view(), name="create"),
    path("monitoring/", views.DocumentDashboardView.as_view(), name="dashboard"),
    path("retention/", views.RetentionRegisterView.as_view(), name="retention"),

    path("<int:pk>/", views.DocumentDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.DocumentUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.DocumentDeleteView.as_view(), name="delete"),

    # Files are served through the application, never straight from MEDIA_URL,
    # so access is re-checked and the download reaches the document's trail.
    path("<int:pk>/download/", views.DocumentDownloadView.as_view(), name="download"),
    path(
        "<int:pk>/versions/<int:version_pk>/",
        views.VersionDownloadView.as_view(),
        name="version_download",
    ),
    # The same files shown in the in-system PDF viewer, under the same checks.
    path("<int:pk>/view/", views.DocumentFileView.as_view(), name="view_file"),
    # Files captured from Incoming and Outgoing Monitoring, and every file at once.
    path(
        "<int:pk>/files/<int:file_pk>/",
        views.SupportingFileDownloadView.as_view(),
        name="supporting_download",
    ),
    path(
        "<int:pk>/files/<int:file_pk>/view/",
        views.SupportingFileView.as_view(),
        name="supporting_view",
    ),
    path("files/", views.FileLibraryView.as_view(), name="files"),
    path(
        "<int:pk>/versions/<int:version_pk>/view/",
        views.VersionFileView.as_view(),
        name="version_view",
    ),

    # Workflow actions. Each is its own POST endpoint rather than a status
    # field on a form, so the trail records what was intended, not merely that
    # a column changed.
    path("<int:pk>/submit-review/", views.SubmitForReviewView.as_view(),
         name="submit_for_review"),
    path("<int:pk>/review/", views.ReviewView.as_view(), name="review"),
    path("<int:pk>/assign/", views.AssignView.as_view(), name="assign"),
    path("<int:pk>/start/", views.StartProcessingView.as_view(), name="start"),
    path("<int:pk>/submit-approval/", views.SubmitForApprovalView.as_view(),
         name="submit_for_approval"),
    path("<int:pk>/complete/", views.CompleteView.as_view(), name="complete"),
    path("<int:pk>/cancel/", views.CancelView.as_view(), name="cancel"),
    path("<int:pk>/upload-version/", views.UploadVersionView.as_view(),
         name="upload_version"),

    # Retention, archiving and disposal.
    path("<int:pk>/retention/", views.SetRetentionView.as_view(),
         name="set_retention"),
    path("<int:pk>/archive/", views.ArchiveView.as_view(), name="archive"),
    path("<int:pk>/restore/", views.RestoreView.as_view(), name="restore"),
    path("<int:pk>/dispose/", views.DisposeView.as_view(), name="dispose"),
]
