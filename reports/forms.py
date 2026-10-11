from core.forms_base import GovModelForm
from documents.forms import ACCEPT_ATTRIBUTE, FORMAT_HELP, validate_upload

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].help_text = FORMAT_HELP
        self.fields["file"].widget.attrs["accept"] = ACCEPT_ATTRIBUTE

    def clean_file(self):
        return validate_upload(self.cleaned_data.get("file"))
