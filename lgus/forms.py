from django import forms

from core.forms_base import GovModelForm

from .models import LGU


class LGUForm(GovModelForm):
    class Meta:
        model = LGU
        fields = [
            "name", "lgu_type", "province", "is_independent", "income_class",
            "address", "contact_person", "contact_position", "contact_number", "email",
            "compliance_status", "is_active", "notes",
        ]

    fieldsets = [
        ("LGU Identification", ["name", "lgu_type", "province", "income_class", "is_independent"]),
        ("Contact Information", ["address", "contact_person", "contact_position",
                                 "contact_number", "email"]),
        ("Oversight", ["compliance_status", "is_active", "notes"]),
    ]
    wide_fields = ("address", "notes")
