from django.urls import path

from . import views

app_name = "programs"

urlpatterns = [
    path("", views.ProgramListView.as_view(), name="list"),
    path("new/", views.ProgramCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ProgramDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProgramUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.ProgramDeleteView.as_view(), name="delete"),
]
