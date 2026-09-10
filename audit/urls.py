from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.AuditListView.as_view(), name="list"),
    path("<int:pk>/", views.AuditDetailView.as_view(), name="detail"),
]
