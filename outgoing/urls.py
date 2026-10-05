from django.urls import path

from . import views

app_name = "outgoing"

urlpatterns = [
    path("", views.OutgoingListView.as_view(), name="list"),
    path("<int:pk>/", views.OutgoingDetailView.as_view(), name="detail"),
    # Action on a document moved here when its focal person acknowledged it.
    path("<int:pk>/update/", views.AddUpdateView.as_view(), name="add_update"),
    path("<int:pk>/return/", views.ReturnView.as_view(), name="return"),
    path("<int:pk>/sent/", views.TransmittalView.as_view(), name="transmittal"),
    path("<int:pk>/file/", views.OutgoingFileView.as_view(), name="view_file"),
]
