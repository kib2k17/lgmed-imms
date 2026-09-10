from django.urls import path

from . import views

app_name = "lgus"

urlpatterns = [
    path("", views.LGUListView.as_view(), name="list"),
    path("new/", views.LGUCreateView.as_view(), name="create"),
    path("<int:pk>/", views.LGUDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.LGUUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.LGUDeleteView.as_view(), name="delete"),
]
