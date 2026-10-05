"""
e-SIRA forms. They validate input and nothing else - every decision about
whether an action is allowed belongs to esira.workflow.
"""

from django import forms
from django.conf import settings

from accounts.models import User
from core.forms_base import (
    CHECKBOX_CLASS,
    ERROR_CLASS,
    FILE_CLASS,
    SELECT_CLASS,
    TEXT_CLASS,
    TEXTAREA_CLASS,
)
from programs.forms import MultipleFileField

from .models import StepAction


class GovForm(forms.Form):
    """A plain form styled like `core.forms_base.GovModelForm`."""

    textarea_rows = 3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prepare_fields()
        for name, field in self.fields.items():
            widget = field.widget
            attrs = widget.attrs
            if isinstance(widget, forms.CheckboxInput):
                attrs["class"] = CHECKBOX_CLASS
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                attrs["class"] = SELECT_CLASS
            elif isinstance(widget, forms.Textarea):
                attrs["class"] = TEXTAREA_CLASS
                attrs["rows"] = self.textarea_rows
                attrs.pop("cols", None)
            elif isinstance(widget, (forms.FileInput, forms.ClearableFileInput)):
                attrs["class"] = FILE_CLASS
            elif isinstance(widget, forms.RadioSelect):
                pass
            else:
                attrs["class"] = TEXT_CLASS
            if isinstance(widget, forms.DateInput):
                widget.input_type = "date"
            if field.required:
                attrs["aria-required"] = "true"
            if field.help_text:
                attrs["aria-describedby"] = f"id_{self.add_prefix(name)}-help"
            if self.is_bound and self.errors.get(name):
                attrs["class"] = attrs.get("class", "") + " " + ERROR_CLASS
                attrs["aria-invalid"] = "true"

    def prepare_fields(self):
        """
        Set querysets and choices here, not after `super().__init__()`.

        The styling loop reads `self.errors`, which validates a bound form; a
        queryset assigned afterwards would be too late, and every choice would
        be refused. See core.forms_base.GovModelForm.prepare_fields.
        """


def active_users():
    return User.objects.filter(is_active=True).order_by("last_name", "first_name", "username")


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        extra = user.position or user.get_role_display()
        return f"{user.get_display_name()} - {extra}"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class UploadForm(GovForm):
    MODE_CHOICES = (
        ("upload", "Upload a PDF"),
        ("scan", "Scan pages (images from a scanner or phone camera)"),
    )

    title = forms.CharField(max_length=255)
    document_type = forms.CharField(
        max_length=120, required=False,
        help_text="e.g. Memorandum, Letter, Certification, Report.",
    )
    description = forms.CharField(
        widget=forms.Textarea, required=False,
        help_text="What the document is and why it is being signed.",
    )
    mode = forms.ChoiceField(
        choices=MODE_CHOICES, initial="upload", widget=forms.RadioSelect,
        label="How is the document coming in?",
    )
    pdf_file = forms.FileField(
        required=False, label="PDF file",
        widget=forms.ClearableFileInput(attrs={"accept": "application/pdf,.pdf"}),
    )
    scan_images = MultipleFileField(
        required=False, label="Scanned pages",
        help_text=(
            "Select the page images in page order - JPEG, PNG or TIFF, from a "
            "scanner or a phone camera. They are assembled into one PDF."
        ),
    )

    def prepare_fields(self):
        self.fields["scan_images"].widget.attrs.update(
            {"accept": "image/jpeg,image/png,image/tiff"}
        )
        self.fields["pdf_file"].help_text = (
            f"Up to {settings.ESIRA_MAX_UPLOAD_MB} MB. Password-protected PDFs "
            "cannot be signed."
        )

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")
        if mode == "upload":
            upload = cleaned.get("pdf_file")
            if not upload:
                self.add_error("pdf_file", "Choose the PDF to upload.")
            elif not upload.name.lower().endswith(".pdf"):
                self.add_error("pdf_file", "The file must be a PDF.")
        elif mode == "scan" and not cleaned.get("scan_images"):
            self.add_error("scan_images", "Choose at least one scanned page.")
        return cleaned


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class RouteStepForm(GovForm):
    recipient = UserChoiceField(queryset=User.objects.none())
    action = forms.ChoiceField(choices=StepAction.choices, label="Action required")
    purpose = forms.CharField(
        max_length=255, required=False, label="Purpose / instructions",
    )
    due_date = forms.DateField(required=False, widget=forms.DateInput)

    def prepare_fields(self):
        self.fields["recipient"].queryset = active_users()


RouteFormSet = forms.formset_factory(
    RouteStepForm, extra=0, min_num=1, validate_min=True, can_delete=True,
    max_num=30, validate_max=True,
)


# ---------------------------------------------------------------------------
# Acting on a step
# ---------------------------------------------------------------------------


class ActForm(GovForm):
    decision = forms.ChoiceField(
        choices=(("complete", "Complete"), ("reject", "Reject")),
        widget=forms.HiddenInput,
    )
    remarks = forms.CharField(
        widget=forms.Textarea, required=False,
        help_text="Required when rejecting. Recorded on the routing slip.",
    )
    forward_to = UserChoiceField(
        queryset=User.objects.none(), required=False,
        label="Forward to (optional)",
        help_text="Send the document to one more person after you.",
    )
    forward_action = forms.ChoiceField(
        choices=StepAction.choices, required=False, initial=StepAction.APPROVE,
        label="Their action",
    )
    forward_purpose = forms.CharField(max_length=255, required=False, label="Instructions")

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def prepare_fields(self):
        queryset = active_users()
        if self.user is not None:
            queryset = queryset.exclude(pk=self.user.pk)
        self.fields["forward_to"].queryset = queryset

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "reject" and not (cleaned.get("remarks") or "").strip():
            self.add_error("remarks", "Give the reason for rejecting the document.")
        return cleaned


class SignForm(GovForm):
    """
    The signer's credential, presented at the moment of signing.

    Nothing here is stored: the file and passphrase go straight to the signing
    backend and are dropped when the request ends.
    """

    certificate_file = forms.FileField(
        required=False, label="PNPKI certificate file (.p12 / .pfx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".p12,.pfx,application/x-pkcs12"}),
    )
    passphrase = forms.CharField(
        required=False, strip=False, label="Certificate passphrase",
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
    )
    reason = forms.CharField(
        max_length=255, required=False, label="Reason for signing",
        help_text="Written into the signature, e.g. Approved, Noted, Certified correct.",
    )
    remarks = forms.CharField(widget=forms.Textarea, required=False, label="Remarks")
    confirm = forms.BooleanField(
        label=(
            "I am signing this document myself, with my own PNPKI certificate, "
            "and I have read its contents."
        ),
    )

    def __init__(self, *args, **kwargs):
        self.collects_credentials = kwargs.pop("collects_credentials", True)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if self.collects_credentials:
            if not cleaned.get("certificate_file"):
                self.add_error("certificate_file", "Select your PNPKI certificate file.")
            if not cleaned.get("passphrase"):
                self.add_error("passphrase", "Enter the certificate passphrase.")
        return cleaned


class CancelForm(GovForm):
    reason = forms.CharField(widget=forms.Textarea, label="Reason for cancelling")


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


class CertificateRegisterForm(GovForm):
    KIND_CHOICES = (
        ("pkcs12", "My PNPKI certificate file (.p12 / .pfx) and its passphrase"),
        ("certificate", "The public certificate only (.cer / .crt / .pem)"),
    )

    kind = forms.ChoiceField(
        choices=KIND_CHOICES, initial="pkcs12", widget=forms.RadioSelect,
        label="What are you registering from?",
    )
    certificate_file = forms.FileField(label="Certificate file")
    passphrase = forms.CharField(
        required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
        help_text=(
            "Needed for a .p12 / .pfx file, to prove the file is yours. Only the "
            "public certificate is kept; the private key is not stored."
        ),
    )

    def clean_certificate_file(self):
        upload = self.cleaned_data["certificate_file"]
        if upload.size > 256 * 1024:
            raise forms.ValidationError("A certificate file is never this large.")
        return upload


class CertificateReviewForm(GovForm):
    decision = forms.ChoiceField(
        choices=(("verify", "Verify"), ("reject", "Reject"), ("revoke", "Revoke")),
        widget=forms.HiddenInput,
    )
    remarks = forms.CharField(max_length=500, required=False)
