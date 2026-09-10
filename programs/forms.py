from django import forms

from core.forms_base import GovModelForm

from .models import Program


class ProgramForm(GovModelForm):
    class Meta:
        model = Program
        fields = [
            "title", "reference_number", "category", "description", "objectives",
            "start_date", "end_date", "status",
            "lead_office", "focal_person", "covered_lgus",
        ]
        widgets = {
            "covered_lgus": forms.SelectMultiple(attrs={"size": 10}),
        }

    fieldsets = [
        ("Program Information", ["title", "reference_number", "category",
                                 "description", "objectives"]),
        ("Implementation Period", ["start_date", "end_date", "status"]),
        ("Responsibility and Coverage", ["lead_office", "focal_person", "covered_lgus"]),
    ]
    wide_fields = ("title", "covered_lgus")

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error(
                "end_date",
                "The end date must not be earlier than the start date.",
            )
        return cleaned
