from core.forms_base import GovModelForm
from documents.forms import ACCEPT_ATTRIBUTE, FORMAT_HELP, validate_upload

from .models import MonitoringActivity, MonitoringAttachment


class MonitoringActivityForm(GovModelForm):
    class Meta:
        model = MonitoringActivity
        fields = [
            "title", "reference_number", "lgu", "program",
            "monitoring_date", "monitoring_team",
            "findings", "recommendations", "follow_up_action", "follow_up_date",
            "status",
        ]

    fieldsets = [
        ("Activity Details", ["title", "reference_number", "lgu", "program",
                              "monitoring_date", "monitoring_team"]),
        ("Findings and Recommendations", ["findings", "recommendations"]),
        ("Follow-up", ["follow_up_action", "follow_up_date", "status"]),
    ]
    wide_fields = ("title",)

    def clean(self):
        cleaned = super().clean()
        activity_date = cleaned.get("monitoring_date")
        follow_up = cleaned.get("follow_up_date")
        if activity_date and follow_up and follow_up < activity_date:
            self.add_error(
                "follow_up_date",
                "The follow-up date must not be earlier than the monitoring date.",
            )
        return cleaned


class MonitoringAttachmentForm(GovModelForm):
    class Meta:
        model = MonitoringAttachment
        fields = ["title", "file"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].help_text = FORMAT_HELP
        self.fields["file"].widget.attrs["accept"] = ACCEPT_ATTRIBUTE

    def clean_file(self):
        return validate_upload(self.cleaned_data.get("file"))
