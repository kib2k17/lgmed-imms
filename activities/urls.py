from django.urls import path

from . import views

app_name = "activities"

urlpatterns = [
    path("", views.CalendarView.as_view(), name="list"),
    path("new/", views.ActivityCreateView.as_view(), name="create"),
    path("monitor/", views.ActivityMonitorView.as_view(), name="monitor"),
    path("<int:pk>/", views.ActivityDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ActivityUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.ActivityDeleteView.as_view(), name="delete"),
    path("<int:pk>/progress/", views.ActivityProgressView.as_view(), name="progress"),
]
