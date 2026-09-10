from django.urls import path

from . import views

app_name = "incoming"

urlpatterns = [
    path("", views.IncomingListView.as_view(), name="list"),
    path("new/", views.IncomingCreateView.as_view(), name="create"),
    path("dashboard/", views.IncomingDashboardView.as_view(), name="dashboard"),
    path("reports/", views.IncomingReportsView.as_view(), name="reports"),
    path("<int:pk>/", views.IncomingDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.IncomingUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.IncomingDeleteView.as_view(), name="delete"),

    # Workflow actions. Each is its own POST endpoint rather than a status
    # field on a form, so the trail records what was intended, not merely that
    # a column changed.
    path("<int:pk>/review/", views.ReviewView.as_view(), name="review"),
    path("<int:pk>/assign/", views.AssignView.as_view(), name="assign"),
    path("<int:pk>/acknowledge/", views.AcknowledgeView.as_view(), name="acknowledge"),
    path("<int:pk>/update/", views.AddUpdateView.as_view(), name="add_update"),
    path("<int:pk>/return/", views.ReturnView.as_view(), name="return"),
]
