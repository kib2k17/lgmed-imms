from django.urls import path

from . import views

app_name = "datasync"

urlpatterns = [
    path("", views.SyncHomeView.as_view(), name="home"),
    path("<int:pk>/", views.BatchView.as_view(), name="batch"),
    path("<int:pk>/sheets/", views.SheetSelectionView.as_view(), name="sheets"),
    path("<int:pk>/commit/", views.CommitView.as_view(), name="commit"),
    path("<int:pk>/discard/", views.DiscardView.as_view(), name="discard"),
    path("<int:pk>/error-report/", views.ErrorReportView.as_view(), name="error_report"),
]
