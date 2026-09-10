from django.urls import path

from . import views

app_name = "monitoring"

urlpatterns = [
    path("", views.MonitoringListView.as_view(), name="list"),
    path("new/", views.MonitoringCreateView.as_view(), name="create"),
    path("<int:pk>/", views.MonitoringDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.MonitoringUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.MonitoringDeleteView.as_view(), name="delete"),
    path("<int:pk>/attachments/add/", views.AttachmentCreateView.as_view(),
         name="attachment_add"),
    path("<int:pk>/attachments/<int:attachment_pk>/delete/",
         views.AttachmentDeleteView.as_view(), name="attachment_delete"),
]
