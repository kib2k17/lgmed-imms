"""
The forms of the Document Management module.

The registration form is an ordinary `GovModelForm`. The workflow forms are
deliberately small and separate - one per decision - because a single form
carrying "status", "focal person", "retention decision" and "disposal
authority" invites a person to change four unrelated things in one submission
and leaves a trail that cannot say which of them they meant.
"""

import os

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from accounts.models import Section
from core.forms_base import GovModelForm
from core.uploads import check_signature

from .models import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    DisposalAuthority,
    Document,
    DocumentStatus,
    DocumentType,
    RetentionDisposition,
)

ACCEPT_ATTRIBUTE = ",".join(f".{extension}" for extension in ALLOWED_EXTENSIONS)

FORMAT_HELP = (
    "PDF, Word, Excel, PowerPoint or an image (JPG, PNG, TIFF). "
    f"Up to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
)


def validate_upload(uploaded):
    """
    Check an uploaded file against the module's accepted formats and size.

    Shared by every form that takes a file, so the register cannot end up
    holding something the download view will not serve.
    """
    # Only a file arriving now is judged. A record's existing file comes back
    # unchanged on every edit and was accepted under the rules of its day.
    if not uploaded or not isinstance(uploaded, UploadedFile):
        return uploaded

    extension = os.path.splitext(uploaded.name)[1].lstrip(".").lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise forms.ValidationError(
            f"'{extension or uploaded.name}' is not an accepted document "
            f"format. {FORMAT_HELP}"
        )
    if uploaded.size > MAX_UPLOAD_BYTES:
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise forms.ValidationError(
            f"This file is {uploaded.size / (1024 * 1024):.1f} MB. "
            f"The limit is {limit} MB."
        )
    return check_signature(uploaded)


class DocumentFileField(forms.FileField):
    """A file input that already knows what the register accepts."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("help_text", FORMAT_HELP)
        super().__init__(*args, **kwargs)
        self.widget.attrs["accept"] = ACCEPT_ATTRIBUTE

    def clean(self, data, initial=None):
        return validate_upload(super().clean(data, initial))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class DocumentForm(GovModelForm):
    """
    Register a document, or correct one already registered.

    Status is not on the form. A document comes into being as a draft or as
    received, and moves on through the workflow actions on its own record -
    which is what makes the trail able to say why each move was made.
    """

    class Meta:
        model = Document
        fields = [
            "title", "document_type", "reference_number", "subject", "sender",
            "date_received", "date_created", "due_date", "year",
            "owner", "unit", "office",
            "file", "description", "remarks", "is_public",
        ]
        widgets = {
            "date_received": forms.DateInput(),
            "date_created": forms.DateInput(),
            "due_date": forms.DateInput(),
        }

    fieldsets = [
        ("Document Information",
         ["title", "document_type", "reference_number", "subject", "sender"]),
        ("Dates", ["date_received", "date_created", "due_date", "year"]),
        ("Ownership and Unit", ["owner", "unit", "office"]),
        ("File and Details", ["file", "description", "remarks", "is_public"]),
    ]
    wide_fields = ("title", "subject", "file")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def prepare_fields(self):
        from .workflow import focal_persons

        registered = bool(self.instance.pk)
        self.fields["file"] = DocumentFileField(
            label="Document file",
            required=False,
            help_text=(
                FORMAT_HELP + (
                    " Replacing the file creates a new version; the one it "
                    "replaces is kept."
                    if registered
                    else ""
                )
            ),
        )
        self.fields["document_type"].queryset = DocumentType.objects.filter(
            is_active=True
        )
        self.fields["unit"].queryset = Section.objects.filter(is_active=True)
        self.fields["owner"].queryset = focal_persons()
        self.fields["year"].required = False
        self.fields["year"].help_text = (
            "Left blank, taken from the date received or the date of the document."
        )
        self.fields["reference_number"].required = False

        if not registered:
            # A document cannot be published at the moment it is registered -
            # publication follows approval - so the checkbox is not offered
            # rather than being offered and then always refused.
            self.fields.pop("is_public", None)
            if self.user is not None:
                self.fields["owner"].initial = self.user.pk
                self.fields["date_received"].initial = timezone.localdate()

    def clean_year(self):
        """Fall back to the document's own dates rather than demanding a year."""
        year = self.cleaned_data.get("year")
        if year:
            return year
        for key in ("date_received", "date_created"):
            value = self.data.get(key)
            if value:
                try:
                    return int(str(value)[:4])
                except ValueError:
                    continue
        return timezone.localdate().year

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_public") and self.instance.status != DocumentStatus.COMPLETED:
            self.add_error(
                "is_public",
                "Only a completed document can be offered on the public "
                "website. Approve it first.",
            )

        received = cleaned.get("date_received")
        created = cleaned.get("date_created")
        if received and created and created > received:
            self.add_error(
                "date_created",
                "The date on the document cannot be later than the date it "
                "was received.",
            )
        return cleaned


# ---------------------------------------------------------------------------
# Workflow forms
# ---------------------------------------------------------------------------


class ReviewForm(forms.Form):
    notes = forms.CharField(
        label="Review notes",
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        help_text="What the document requires, for whoever is assigned to it.",
    )


class AssignmentForm(forms.Form):
    """The Chief names the focal person and, if there is one, sets the deadline."""

    assigned_to = forms.ModelChoiceField(
        label="Assigned personnel / focal person",
        queryset=None,
        empty_label="Select a focal person",
    )
    assignment_remarks = forms.CharField(
        label="Instructions",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )
    due_date = forms.DateField(
        label="Action due date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .workflow import focal_persons

        self.fields["assigned_to"].queryset = focal_persons()


class VersionUploadForm(forms.Form):
    """
    Supersede the document's file.

    The reason is required. A version history whose entries say nothing about
    why the file changed records that it changed and no more, which is the
    part nobody needed help remembering.
    """

    file = DocumentFileField(label="New version of the document")
    reason = forms.CharField(
        label="Reason for revision",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="What changed in this version, and why.",
    )


class StatusNoteForm(forms.Form):
    """Used by the simple moves - start processing, submit for approval, approve."""

    notes = forms.CharField(
        label="Remarks",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )


class CancelForm(forms.Form):
    reason = forms.CharField(
        label="Reason for cancellation",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded on the document's trail.",
    )


# ---------------------------------------------------------------------------
# Retention, archiving and disposal
# ---------------------------------------------------------------------------


class RetentionForm(forms.Form):
    """The records officer's decision about a document's long-term fate."""

    retention_until = forms.DateField(
        label="Retention period ends",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Leave blank for a document with no fixed period.",
    )
    retention_disposition = forms.ChoiceField(
        label="Retention decision",
        choices=[
            (value, label)
            for value, label in RetentionDisposition.choices
            # Disposal is an act, not a decision to be selected here: a
            # document becomes "Disposed" by being disposed of, under an
            # authority, and never by someone choosing it from a menu.
            if value != RetentionDisposition.DISPOSED
        ],
    )
    notes = forms.CharField(
        label="Notes",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )


class ArchiveForm(forms.Form):
    reason = forms.CharField(
        label="Reason for archiving",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        help_text=(
            "The document, its versions and its trail are all kept. Only "
            "access to it is restricted."
        ),
    )


class RestoreForm(forms.Form):
    reason = forms.CharField(
        label="Reason for restoring",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Why the document is being brought back into circulation.",
    )


class DisposalForm(forms.Form):
    """
    Permanent disposal.

    Three separate things are asked for - the authority, the notes and a typed
    confirmation - because this is the only action in the system that cannot
    be undone, and it should not be possible to complete it by clicking
    through without reading.
    """

    CONFIRMATION = "DISPOSE"

    authority = forms.ModelChoiceField(
        label="Disposal authority",
        queryset=DisposalAuthority.objects.filter(is_active=True),
        empty_label="Select the authority for this disposal",
        help_text=(
            "The written authority under which this document is disposed of. "
            "Recorded against the document permanently."
        ),
    )
    notes = forms.CharField(
        label="Disposal notes",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )
    confirmation = forms.CharField(
        label=f"Type {CONFIRMATION} to confirm",
        help_text=(
            "The document's file will be destroyed. Its record, ownership, "
            "version list and trail are kept."
        ),
    )

    def clean_confirmation(self):
        value = self.cleaned_data.get("confirmation", "").strip().upper()
        if value != self.CONFIRMATION:
            raise forms.ValidationError(
                f"Type {self.CONFIRMATION} exactly to confirm the disposal."
            )
        return value


class DisposalAuthorityForm(GovModelForm):
    """Maintained in System Settings, beside the other reference lists."""

    class Meta:
        model = DisposalAuthority
        fields = [
            "reference", "title", "approved_on", "approved_by", "notes",
            "is_active",
        ]
        widgets = {"approved_on": forms.DateInput()}
