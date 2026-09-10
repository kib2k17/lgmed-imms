from core.forms_base import GovModelForm

from .models import Report


class ReportForm(GovModelForm):
    class Meta:
        model = Report
        fields = [
            "title", "reference_number", "period", "year", "program", "summary",
            "prepared_by", "file", "status", "review_remarks",
        ]

    fieldsets = [
        ("Report Information", ["title", "reference_number", "period", "year",
                                "program", "summary"]),
        ("Submission", ["prepared_by", "file", "status", "review_remarks"]),
    ]
    wide_fields = ("title", "file")
