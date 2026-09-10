from django.urls import path

from . import views

app_name = "services"

urlpatterns = [
    path("", views.ServiceListView.as_view(), name="list"),
    path("new/", views.ServiceCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ServiceDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ServiceUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.ServiceDeleteView.as_view(), name="delete"),
]
