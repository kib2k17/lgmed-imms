from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("<int:pk>/open/", views.open_notification, name="open"),
    path("<int:pk>/dismiss/", views.dismiss_notification, name="dismiss"),
    path("read-all/", views.mark_all_read, name="read_all"),
    path("status/", views.notification_status, name="status"),
]
