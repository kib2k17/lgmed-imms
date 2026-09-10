from django.urls import path

from . import views

app_name = "updates"

urlpatterns = [
    # The Division's figures.
    path("", views.DivisionDashboardView.as_view(), name="dashboard"),

    # The entries staff contribute.
    path("entries/", views.DivisionUpdateListView.as_view(), name="list"),
    path("entries/new/", views.DivisionUpdateCreateView.as_view(), name="create"),
    path("entries/<int:pk>/", views.DivisionUpdateDetailView.as_view(), name="detail"),
    path(
        "entries/<int:pk>/edit/",
        views.DivisionUpdateUpdateView.as_view(),
        name="update",
    ),
    path(
        "entries/<int:pk>/delete/",
        views.DivisionUpdateDeleteView.as_view(),
        name="delete",
    ),
    path(
        "entries/<int:pk>/attach/",
        views.AttachmentCreateView.as_view(),
        name="attachment_add",
    ),
    path(
        "attachments/<int:pk>/delete/",
        views.AttachmentDeleteView.as_view(),
        name="attachment_delete",
    ),

    # The weeks those entries are consolidated into.
    path("weeks/", views.PeriodListView.as_view(), name="period_list"),
    path("weeks/new/", views.PeriodCreateView.as_view(), name="period_create"),
    path("weeks/<int:pk>/", views.PeriodDetailView.as_view(), name="period_detail"),
    path(
        "weeks/<int:pk>/edit/",
        views.PeriodUpdateView.as_view(),
        name="period_update",
    ),
    path(
        "weeks/<int:pk>/delete/",
        views.PeriodDeleteView.as_view(),
        name="period_delete",
    ),
    path("weeks/<int:pk>/submit/", views.PeriodSubmitView.as_view(), name="submit"),

    # The Division Chief.
    path("weeks/<int:pk>/review/", views.PeriodReviewView.as_view(), name="review"),
    path(
        "public-disclosure/",
        views.PublicDisclosureView.as_view(),
        name="disclosure",
    ),

    # The Monday convocation, with and without a week named.
    path("convocation/", views.ConvocationView.as_view(), name="convocation_latest"),
    path(
        "weeks/<int:pk>/convocation/",
        views.ConvocationView.as_view(),
        name="convocation",
    ),

    # Records that belong to the week rather than to one entry.
    path("weeks/<int:pk>/pops/new/", views.PopsCreateView.as_view(), name="pops_create"),
    path("pops/<int:pk>/edit/", views.PopsUpdateView.as_view(), name="pops_update"),
    path("pops/<int:pk>/delete/", views.PopsDeleteView.as_view(), name="pops_delete"),
    path(
        "weeks/<int:pk>/ways-forward/new/",
        views.WayForwardCreateView.as_view(),
        name="way_create",
    ),
    path(
        "ways-forward/<int:pk>/edit/",
        views.WayForwardUpdateView.as_view(),
        name="way_update",
    ),
    path(
        "ways-forward/<int:pk>/delete/",
        views.WayForwardDeleteView.as_view(),
        name="way_delete",
    ),
]
