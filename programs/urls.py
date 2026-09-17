"""
Internal routes for the PPA module.

The four levels share one set of routes, keyed on a `<level>` segment that is
resolved against `views.LEVELS`. A level that is not one of the four is a 404
before any view runs.

Note what has no route at all: the internal file. There is no URL that maps to
the protected directory, and `document_download` is a view that opens the file
itself after checking the session and the role.
"""

from django.urls import path, register_converter

from . import views


class LevelConverter:
    """Matches exactly the four levels, so a bad one never reaches a view."""

    regex = "program|project|sub-project|activity"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(LevelConverter, "level")

app_name = "programs"

urlpatterns = [
    # The tree.
    path("", views.WorkbenchView.as_view(), name="list"),
    path("queue/", views.ReviewQueueView.as_view(), name="queue"),

    # Creating: a programme stands alone, everything else is created under a
    # named parent so an orphan cannot be made.
    path("program/new/", views.RecordCreateView.as_view(), {"level": "program"},
         name="program_create"),
    path("<level:parent_level>/<int:parent_pk>/add/<level:level>/",
         views.RecordCreateView.as_view(), name="create_child"),

    # One record.
    path("<level:level>/<int:pk>/", views.RecordDetailView.as_view(), name="detail"),
    path("<level:level>/<int:pk>/edit/", views.RecordUpdateView.as_view(),
         name="update"),
    path("<level:level>/<int:pk>/delete/", views.RecordDeleteView.as_view(),
         name="delete"),
    path("<level:level>/<int:pk>/preview/", views.RecordPreviewView.as_view(),
         name="preview"),

    # The workflow. All POST-only: a state change must never be something a
    # crawler, a prefetching browser or a mistyped address can cause.
    path("<level:level>/<int:pk>/submit/", views.RecordSubmitView.as_view(),
         name="submit"),
    path("<level:level>/<int:pk>/decide/", views.RecordDecisionView.as_view(),
         name="decide"),
    path("<level:level>/<int:pk>/publish/", views.RecordPublishView.as_view(),
         name="publish"),
    path("<level:level>/<int:pk>/unpublish/", views.RecordUnpublishView.as_view(),
         name="unpublish"),
    path("<level:level>/<int:pk>/archive/", views.RecordArchiveView.as_view(),
         name="archive"),
    path("<level:level>/<int:pk>/restore/", views.RecordRestoreView.as_view(),
         name="restore"),

    # The written authority to publish. Its own pages, ahead of any release
    # that cites it - a memorandum recorded inside the act it authorises is
    # not an authority.
    path("authorities/", views.AuthorityListView.as_view(), name="authority_list"),
    path("authorities/new/", views.AuthorityCreateView.as_view(),
         name="authority_create"),
    path("authorities/<int:pk>/", views.AuthorityDetailView.as_view(),
         name="authority_detail"),
    path("authorities/<int:pk>/edit/", views.AuthorityUpdateView.as_view(),
         name="authority_update"),
    path("authorities/<int:pk>/memorandum/", views.AuthorityFileView.as_view(),
         name="authority_file"),

    # Documents.
    path("<level:level>/<int:pk>/documents/new/",
         views.DocumentUploadView.as_view(), name="document_upload"),
    # The running order of a record's photographs. Its own page, and an
    # encoder's to use: arranging a gallery is an editorial act and must not
    # be reachable only from a screen that also publishes things.
    path("<level:level>/<int:pk>/photographs/arrange/",
         views.PhotoArrangeView.as_view(), name="photo_arrange"),
    path("documents/<int:pk>/", views.DocumentReviewView.as_view(),
         name="document_review"),
    path("documents/<int:pk>/rescreen/", views.DocumentRescreenView.as_view(),
         name="document_rescreen"),
    path("documents/<int:pk>/authority/", views.DocumentAuthorityView.as_view(),
         name="document_authority"),
    # Releasing or withdrawing one file, without disturbing the record that
    # carries it - a programme is published once and added to for months.
    path("documents/<int:pk>/publish/", views.DocumentPublishView.as_view(),
         name="document_publish"),
    path("documents/<int:pk>/withdraw/", views.DocumentWithdrawView.as_view(),
         name="document_withdraw"),
    path("documents/<int:pk>/delete/", views.DocumentDeleteView.as_view(),
         name="document_delete"),
    path("documents/<int:pk>/file/", views.DocumentDownloadView.as_view(),
         name="document_download"),
]

# Backwards compatibility: the first version of this module routed programmes
# at /app/programs/<pk>/. Keeping the old names pointing at the new views means
# a bookmark, an email link or an audit-log entry from before the rebuild still
# lands on the right page.
urlpatterns += [
    path("<int:pk>/", views.RecordDetailView.as_view(), {"level": "program"},
         name="program_detail"),
    path("<int:pk>/edit/", views.RecordUpdateView.as_view(), {"level": "program"},
         name="program_update"),
    path("project/<int:pk>/", views.RecordDetailView.as_view(), {"level": "project"},
         name="project_detail"),
    path("sub-project/<int:pk>/", views.RecordDetailView.as_view(),
         {"level": "sub-project"}, name="subproject_detail"),
    path("activity/<int:pk>/", views.RecordDetailView.as_view(),
         {"level": "activity"}, name="activity_detail"),
]
