from django.urls import path

from . import views

app_name = "submissions"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("mine/", views.StaffDashboardView.as_view(), name="mine"),
    path("upload/<int:pk>/", views.UploadView.as_view(), name="upload"),
    path("file/<int:pk>/<str:kind>/", views.SubmissionFileView.as_view(), name="file"),
    path("file/<int:pk>/<str:kind>/view/", views.SubmissionFileInlineView.as_view(),
         name="file_view"),

    # The Division Chief
    path("review/<int:schedule>/<int:staff>/", views.ReviewView.as_view(), name="review"),
    path("remind/", views.SendReminderView.as_view(), name="remind"),
    path("export/", views.ExportView.as_view(), name="export"),
    path("deadlines/", views.ScheduleListView.as_view(), name="schedules"),
    path("deadlines/new/", views.ScheduleCreateView.as_view(), name="schedule_create"),
    path("deadlines/<int:pk>/", views.ScheduleUpdateView.as_view(), name="schedule_update"),
]
