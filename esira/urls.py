from django.urls import path

from . import views

app_name = "esira"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("stats.json", views.StatsView.as_view(), name="stats"),
    path("documents/", views.DocumentListView.as_view(), name="list"),
    path("documents/new/", views.UploadView.as_view(), name="upload"),
    path("documents/<int:pk>/", views.DocumentDetailView.as_view(), name="detail"),
    path("documents/<int:pk>/sign/", views.WorkspaceView.as_view(), name="workspace"),
    path("documents/<int:pk>/file/", views.FileView.as_view(), name="file"),
    path("documents/<int:pk>/boxes/", views.BoxesView.as_view(), name="boxes"),
    path("documents/<int:pk>/verify/", views.VerifyView.as_view(), name="verify"),

    # Workflow actions: each a POST to its own URL, so the trail records what
    # was intended rather than merely that a status changed.
    path("documents/<int:pk>/sign/apply/", views.SignView.as_view(), name="sign"),
    path("documents/<int:pk>/route/", views.RouteView.as_view(), name="route"),
    path("documents/<int:pk>/act/", views.ActView.as_view(), name="act"),
    path("documents/<int:pk>/complete/", views.CompleteView.as_view(), name="complete"),
    path("documents/<int:pk>/cancel/", views.CancelView.as_view(), name="cancel"),

    path("certificates/", views.CertificateListView.as_view(), name="certificates"),
    path("certificates/password/", views.CertificatePasswordView.as_view(), name="certificate_password"),
    path("certificates/signature.png", views.SignatureImageView.as_view(), name="signature_image"),
    path("signature-styles/", views.SignatureStyleView.as_view(), name="signature_styles"),
    path("signature-styles/<int:pk>.png", views.SignatureStyleImageView.as_view(), name="signature_style_image"),
    path("certificates/verification/", views.CertificateReviewView.as_view(), name="certificate_review"),
    path("audit/", views.AuditTrailView.as_view(), name="audit"),
]
