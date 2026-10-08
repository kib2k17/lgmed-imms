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
    The signer's credential for this signature.

    With a certificate on file (`stored`), the file is not asked for, and the
    password only when the signer's profile requires it (`require_passphrase`).
    Otherwise both are presented here. Nothing typed here is stored: it goes
    straight to the signing backend and is dropped when the request ends.
    """

    certificate_file = forms.FileField(
        required=False, label="PNPKI certificate file (.p12 / .pfx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".p12,.pfx,application/x-pkcs12"}),
    )
    passphrase = forms.CharField(
        required=False, strip=False, label="Certificate password (.p12)",
        # "new-password", not "off": browsers ignore "off" on password fields
        # and fill in the saved sign-in password, which is never this one.
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="The password of your .p12 file - not your system sign-in password.",
    )
    reason = forms.CharField(
        max_length=255, required=False, label="Reason for signing",
        help_text="Written into the signature, e.g. Approved, Noted, Certified correct.",
    )
    remarks = forms.CharField(widget=forms.Textarea, required=False, label="Remarks")
    style = forms.ChoiceField(
        required=False, widget=forms.RadioSelect, label="Signature style",
    )
    confirm = forms.BooleanField(
        label=(
            "I am signing this document myself, with my own PNPKI certificate, "
            "and I have read its contents."
        ),
    )

    def __init__(self, *args, **kwargs):
        self.collects_credentials = kwargs.pop("collects_credentials", True)
        self.stored = kwargs.pop("stored", False)
        self.require_passphrase = kwargs.pop("require_passphrase", True)
        # Dicts from workflow.signature_styles; the template draws a preview
        # of each beside its radio button.
        self.styles = kwargs.pop("styles", [])
        super().__init__(*args, **kwargs)

    def prepare_fields(self):
        self.fields["style"].choices = [(s["key"], s["name"]) for s in self.styles]

    @property
    def asks_for_file(self):
        return self.collects_credentials and not self.stored

    @property
    def asks_for_passphrase(self):
        return self.collects_credentials and (not self.stored or self.require_passphrase)

    def clean(self):
        cleaned = super().clean()
        if self.asks_for_file and not cleaned.get("certificate_file"):
            self.add_error("certificate_file", "Select your PNPKI certificate file.")
        if self.asks_for_passphrase and not cleaned.get("passphrase"):
            self.add_error(
                "passphrase",
                "Enter your .p12 certificate password, or turn off \"Require .p12 "
                "password when signing\" on the My Digital Certificate page.",
            )
        return cleaned


class CancelForm(GovForm):
    reason = forms.CharField(widget=forms.Textarea, label="Reason for cancelling")


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


class CertificateRegisterForm(GovForm):
    """Upload or replace the .p12 / .pfx kept on file, with its password."""

    certificate_file = forms.FileField(
        label="Certificate file (.p12)",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".p12,.pfx,application/x-pkcs12"}
        ),
    )
    passphrase = forms.CharField(
        label="Certificate password", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="The password you set when the certificate was issued or exported.",
    )

    def clean_certificate_file(self):
        upload = self.cleaned_data["certificate_file"]
        if not upload.name.lower().endswith((".p12", ".pfx")):
            raise forms.ValidationError("Choose your .p12 or .pfx certificate file.")
        if upload.size > 256 * 1024:
            raise forms.ValidationError("A certificate file is never this large.")
        return upload


class SignatureImageForm(GovForm):
    signature_image = forms.FileField(
        label="Signature image",
        widget=forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,.png,.jpg,.jpeg"}),
        help_text="PNG or JPG, up to 2 MB. A transparent PNG looks best.",
    )

    def clean_signature_image(self):
        from .signature_images import process_signature_image

        return process_signature_image(self.cleaned_data["signature_image"])


class CertificateReviewForm(GovForm):
    decision = forms.ChoiceField(
        choices=(("verify", "Verify"), ("reject", "Reject"), ("revoke", "Revoke")),
        widget=forms.HiddenInput,
    )
    remarks = forms.CharField(max_length=500, required=False)


class SignatureStyleForm(GovForm):
    """One custom signature style: a name and the picture drawn in the box."""

    name = forms.CharField(
        max_length=80, label="Style name",
        help_text="e.g. your name, or \"Full signature\".",
    )
    image = forms.FileField(
        label="Signature graphic",
        widget=forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,.png,.jpg,.jpeg"}),
        help_text="PNG or JPG, up to 2 MB - e.g. your signature over your printed name.",
    )

    def clean_image(self):
        from .signature_images import process_signature_image

        return process_signature_image(self.cleaned_data["image"])
