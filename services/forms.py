from core.forms_base import GovModelForm

from .models import FrontlineService


class FrontlineServiceForm(GovModelForm):
    class Meta:
        model = FrontlineService
        fields = [
            "name", "service_type", "description", "clients",
            "requirements", "processing_time", "fees",
            "responsible_office", "responsible_person", "is_published",
        ]

    fieldsets = [
        ("Service Information", ["name", "service_type", "description", "clients"]),
        ("Requirements and Processing", ["requirements", "processing_time", "fees"]),
        ("Responsibility", ["responsible_office", "responsible_person", "is_published"]),
    ]
    wide_fields = ("name", "clients")
