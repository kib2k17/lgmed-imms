"""
The forms for each hand the document passes through.

They are deliberately separate rather than one form with fields switched on and
off by role. The encoder's form has no focal-person field at all, so there is
no version of the request that can carry one: the workflow rule is expressed in
the shape of the form, not only in a check.
"""

from django import forms
from django.utils import timezone

from core.forms_base import GovModelForm
from documents.forms import ACCEPT_ATTRIBUTE, FORMAT_HELP, validate_upload

from .models import FOCAL_STATUSES, IncomingDocument, IncomingUpdate, Priority


class IncomingDocumentForm(GovModelForm):
    """
    What the encoder records when a document arrives.

    No focal person, no status, no due date: the Division Chief decides those,
    and a field that is not on the form cannot be filled in by mistake.
    """

    class Meta:
        model = IncomingDocument
        fields = [
            "docket_number", "subject", "document_type", "date_received",
            "source_office", "attachment", "initial_remarks",
        ]
        # The docket number is the office's own handle on the document, so a
        # clash is worth explaining in the office's own terms rather than in
        # Django's ("Incoming document with this Docket number already exists").
        error_messages = {
            "docket_number": {
                "unique": (
                    "A document with this DNS number has already been "
                    "recorded. Search the register for it before recording it "
                    "again."
                ),
            },
        }

    fieldsets = [
        ("Document Details", ["docket_number", "subject", "document_type",
                              "date_received", "source_office"]),
        ("Attachment and Remarks", ["attachment", "initial_remarks"]),
    ]
    wide_fields = ("subject", "attachment")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from documents.models import DocumentType

        self.fields["document_type"].queryset = DocumentType.objects.filter(
            is_active=True
        )
        self.fields["initial_remarks"].label = "Initial remarks"
        self.fields["attachment"].help_text = FORMAT_HELP
        self.fields["attachment"].widget.attrs["accept"] = ACCEPT_ATTRIBUTE

    def clean_attachment(self):
        return validate_upload(self.cleaned_data.get("attachment"))

    def clean_docket_number(self):
        return self.cleaned_data["docket_number"].strip()

    def clean_date_received(self):
        received = self.cleaned_data["date_received"]
        if received and received > timezone.localdate():
            raise forms.ValidationError(
                "A document cannot be recorded as received on a future date."
            )
        return received


class ReviewForm(forms.Form):
    """The Chief's note on what the document is and what it requires."""

    review_notes = forms.CharField(
        label="Notes / instructions",
        widget=forms.Textarea(attrs={"rows": 4}),
        required=True,
        help_text=(
            "What the document requires, and any instruction the focal person "
            "should carry out."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class AssignmentForm(forms.Form):
    """The Chief's decision: who handles this, by when, and with what instruction."""

    assigned_to = forms.ModelChoiceField(
        label="Focal person",
        queryset=None,
        empty_label="Select the focal person...",
        help_text="The officer who will act on this document.",
    )
    assignment_remarks = forms.CharField(
        label="Assignment remarks / instructions",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )
    priority = forms.ChoiceField(choices=Priority.choices, initial=Priority.NORMAL)
    due_date = forms.DateField(
        label="Action due date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Leave empty if no deadline applies. Used for overdue monitoring.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .workflow import focal_persons

        self.fields["assigned_to"].queryset = focal_persons()
        self.fields["assigned_to"].label_from_instance = _person_label
        _style(self)

    def clean_due_date(self):
        due = self.cleaned_data.get("due_date")
        if due and due < timezone.localdate():
            raise forms.ValidationError("The action due date cannot be in the past.")
        return due


class IncomingUpdateForm(GovModelForm):
    """The focal person's report of what has been done."""

    class Meta:
        model = IncomingUpdate
        fields = ["action_taken", "remarks", "status", "attachment"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in self.fields["status"].choices
            if value in FOCAL_STATUSES
        ]
        self.fields["status"].label = "Current status"
        self.fields["action_taken"].widget.attrs["rows"] = 3
        self.fields["remarks"].widget.attrs["rows"] = 2
        self.fields["attachment"].help_text = (
            "Supporting document for this action, if any. " + FORMAT_HELP
        )
        self.fields["attachment"].widget.attrs["accept"] = ACCEPT_ATTRIBUTE

    def clean_attachment(self):
        return validate_upload(self.cleaned_data.get("attachment"))


class ReturnForm(forms.Form):
    """What the Chief wants revised, sent back to the focal person."""

    remarks = forms.CharField(
        label="What needs revision",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


def _person_label(user):
    position = user.position or user.get_role_display()
    return f"{user.get_display_name()} - {position}"


def _style(form):
    """
    Apply the design system's input styling to a plain Form.

    `GovModelForm` does this for model forms; these four are plain forms
    because they act on a record rather than editing its fields directly.
    """
    from core.forms_base import SELECT_CLASS, TEXT_CLASS, TEXTAREA_CLASS

    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("class", TEXTAREA_CLASS)
        elif isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", SELECT_CLASS)
        else:
            widget.attrs.setdefault("class", TEXT_CLASS)
        if field.required:
            widget.attrs["aria-required"] = "true"
