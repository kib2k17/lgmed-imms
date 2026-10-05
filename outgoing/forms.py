"""
The form a focal person fills in when the Division answers an incoming document.

It has no control-code field: the code is the one the Division Chief's
assignment issued to the incoming document, and is set by
`incoming.workflow.open_outgoing`, never typed.
"""

from django import forms
from django.utils import timezone

from core.forms_base import GovModelForm
from documents.forms import ACCEPT_ATTRIBUTE, FORMAT_HELP, validate_upload

from .models import OutgoingDocument


class OutgoingResponseForm(GovModelForm):
    class Meta:
        model = OutgoingDocument
        fields = [
            "date_sent", "communication_type", "subject", "sent_to", "sent_via",
            "dms_number", "remarks", "file",
        ]

    fieldsets = [
        ("Communication", ["date_sent", "communication_type", "subject"]),
        ("Transmittal", ["sent_to", "sent_via", "dms_number", "remarks"]),
        ("File", ["file"]),
    ]
    wide_fields = ("subject", "file")

    def prepare_fields(self):
        self.fields["date_sent"].required = True
        self.fields["date_sent"].help_text = "The date the communication was sent."
        self.fields["subject"].required = True
        self.fields["file"].help_text = (
            "The communication as sent, e.g. the signed and scanned reply. It is "
            f"filed in the Documents register with the incoming document. {FORMAT_HELP}"
        )
        self.fields["file"].widget.attrs["accept"] = ACCEPT_ATTRIBUTE

    def clean_file(self):
        return validate_upload(self.cleaned_data.get("file"))

    def clean_date_sent(self):
        sent = self.cleaned_data["date_sent"]
        if sent and sent > timezone.localdate():
            raise forms.ValidationError(
                "A communication cannot be recorded as sent on a future date."
            )
        return sent
