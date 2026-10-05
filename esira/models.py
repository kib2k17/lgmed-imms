"""
e-SIRA - Electronic Signature, Identification, Routing and Approval.

The tables are separated by what they prove, because each answers a different
question an auditor will ask:

    EsiraDocument     what is being signed, who owns it, and where it stands
    DocumentVersion   the exact bytes at each point - the original upload is
                      version 1 and is never replaced; every signature adds a
                      new version on top of the last
    SignatureBox      WHERE a signature should appear. An interface decision,
                      nothing more: a box proves no one's consent
    RoutingStep       who sent the document to whom, for what, and when each
                      of them received and acted on it
    DigitalSignature  a cryptographic signature actually applied, with the
                      certificate that made it
    SigningCertificate  a PNPKI certificate an employee has registered and an
                      administrator has confirmed is theirs
    AuditEntry        every action on a document, append-only

Versions, signatures and audit entries are write-once. Their `save()` refuses
to update an existing row and their `delete()` refuses outright, so no view,
admin page or shell session can rewrite them by accident.
"""

import hashlib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from programs.storage import protected_storage


class ImmutableRecordError(ValidationError):
    """Raised when something tries to change a write-once record."""


class WriteOnceModel(models.Model):
    """A row that may be created and read, never changed or removed."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise ImmutableRecordError(
                f"{self._meta.verbose_name} records cannot be changed once written."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError(
            f"{self._meta.verbose_name} records cannot be deleted."
        )


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    # The owner's own signature is the next thing due.
    AWAITING_SIGNATURE = "AWAITING_SIGNATURE", "Awaiting Signature"
    # Sent to someone else to sign; nobody has signed yet.
    OUT_FOR_SIGNATURE = "OUT_FOR_SIGNATURE", "Out for Signature"
    # At least one signature applied, more still due.
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED", "Partially Signed"
    # Every signature step done, every step acted on.
    FULLY_SIGNED = "FULLY_SIGNED", "Fully Signed"
    # With someone for approval, review or acknowledgement rather than a
    # signature, and no signature outstanding.
    ROUTED = "ROUTED", "Routed"
    # Every step acted on and none of them was a signature.
    ROUTING_COMPLETED = "ROUTING_COMPLETED", "Routing Completed"
    # Closed by the owner. Nothing further may happen to it.
    COMPLETED = "COMPLETED", "Completed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


TERMINAL_STATUSES = {
    DocumentStatus.COMPLETED,
    DocumentStatus.REJECTED,
    DocumentStatus.CANCELLED,
}

IN_ROUTING_STATUSES = {
    DocumentStatus.AWAITING_SIGNATURE,
    DocumentStatus.OUT_FOR_SIGNATURE,
    DocumentStatus.PARTIALLY_SIGNED,
    DocumentStatus.ROUTED,
}

# Every step acted on; waiting only for the owner to close the file.
FINISHED_STATUSES = {
    DocumentStatus.FULLY_SIGNED,
    DocumentStatus.ROUTING_COMPLETED,
}

# How each status reads as a badge. Keys of core/status.py's STATUS_MAP.
STATUS_TONES = {
    DocumentStatus.DRAFT: "draft",
    DocumentStatus.AWAITING_SIGNATURE: "pending",
    DocumentStatus.OUT_FOR_SIGNATURE: "in_progress",
    DocumentStatus.PARTIALLY_SIGNED: "in_progress",
    DocumentStatus.FULLY_SIGNED: "approved",
    DocumentStatus.ROUTED: "in_progress",
    DocumentStatus.ROUTING_COMPLETED: "approved",
    DocumentStatus.COMPLETED: "completed",
    DocumentStatus.REJECTED: "rejected",
    DocumentStatus.CANCELLED: "cancelled",
}


class StepAction(models.TextChoices):
    SIGN = "SIGN", "Signature"
    APPROVE = "APPROVE", "Approval"
    REVIEW = "REVIEW", "Review / initials"
    ACKNOWLEDGE = "ACKNOWLEDGE", "For information / acknowledgement"


class StepStatus(models.TextChoices):
    # Later in the route; not yet sent to the recipient.
    QUEUED = "QUEUED", "Queued"
    # Sent to the recipient, not yet opened.
    PENDING = "PENDING", "Awaiting action"
    # Opened by the recipient, not yet acted on.
    RECEIVED = "RECEIVED", "Received"
    SIGNED = "SIGNED", "Signed"
    APPROVED = "APPROVED", "Approved"
    REVIEWED = "REVIEWED", "Reviewed"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    REJECTED = "REJECTED", "Rejected"
    # Never reached: the document was rejected or cancelled first.
    CANCELLED = "CANCELLED", "Cancelled"


OPEN_STEP_STATUSES = {StepStatus.PENDING, StepStatus.RECEIVED}
DONE_STEP_STATUSES = {
    StepStatus.SIGNED,
    StepStatus.APPROVED,
    StepStatus.REVIEWED,
    StepStatus.ACKNOWLEDGED,
}
# The status a step takes when its recipient does what was asked.
COMPLETION_STATUS = {
    StepAction.SIGN: StepStatus.SIGNED,
    StepAction.APPROVE: StepStatus.APPROVED,
    StepAction.REVIEW: StepStatus.REVIEWED,
    StepAction.ACKNOWLEDGE: StepStatus.ACKNOWLEDGED,
}

STEP_TONES = {
    StepStatus.QUEUED: "not_started",
    StepStatus.PENDING: "pending",
    StepStatus.RECEIVED: "received",
    StepStatus.SIGNED: "completed",
    StepStatus.APPROVED: "approved",
    StepStatus.REVIEWED: "reviewed",
    StepStatus.ACKNOWLEDGED: "acknowledged",
    StepStatus.REJECTED: "rejected",
    StepStatus.CANCELLED: "cancelled",
}


# ---------------------------------------------------------------------------
# Reference numbers
# ---------------------------------------------------------------------------


class ReferenceSequence(models.Model):
    """The last reference number issued in a year, for ESIRA-2026-0001."""

    year = models.PositiveSmallIntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "e-SIRA reference sequence"

    def __str__(self):
        return f"{self.year}: {self.last_number}"

    @classmethod
    def next_reference(cls):
        """Issue the next number. Row-locked so two uploads never share one."""
        year = timezone.localdate().year
        with transaction.atomic():
            sequence, _ = cls.objects.select_for_update().get_or_create(year=year)
            sequence.last_number += 1
            sequence.save(update_fields=["last_number"])
            return f"ESIRA-{year}-{sequence.last_number:04d}"


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


class EsiraDocumentQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(status__in=TERMINAL_STATUSES)


class EsiraDocument(models.Model):
    reference_no = models.CharField("reference no.", max_length=30, unique=True, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        help_text="What the document is and what it is being signed for.",
    )
    document_type = models.CharField(
        max_length=120, blank=True,
        help_text="e.g. Memorandum, Letter, Certification, Report.",
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="esira_documents",
        help_text="The employee who uploaded the document and controls its route.",
    )
    status = models.CharField(
        max_length=20, choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT, db_index=True,
    )

    # How it entered the system: a PDF as uploaded, or images from a scanner
    # or phone camera assembled into one.
    source = models.CharField(
        max_length=10,
        choices=(("UPLOAD", "Uploaded PDF"), ("SCAN", "Scanned images")),
        default="UPLOAD",
    )
    original_filename = models.CharField(max_length=255, blank=True)
    page_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    routed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    closed_reason = models.TextField(
        blank=True,
        help_text="Why the document was rejected or cancelled.",
    )

    objects = EsiraDocumentQuerySet.as_manager()

    class Meta:
        verbose_name = "e-SIRA document"
        verbose_name_plural = "e-SIRA documents"
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("owner", "status"))]

    def __str__(self):
        return f"{self.reference_no} - {self.title}"

    def get_absolute_url(self):
        return reverse("esira:detail", args=[self.pk])

    # -- state ----------------------------------------------------------

    @property
    def is_terminal(self):
        return self.status in TERMINAL_STATUSES

    @property
    def is_draft(self):
        return self.status == DocumentStatus.DRAFT

    @property
    def is_finished(self):
        return self.status in FINISHED_STATUSES

    @property
    def status_tone(self):
        return STATUS_TONES.get(self.status, "neutral")

    @property
    def original_version(self):
        return self.versions.order_by("number").first()

    @property
    def current_version(self):
        return self.versions.order_by("-number").first()

    @property
    def signature_count(self):
        return self.signatures.count()

    def current_step(self):
        return (
            self.steps.filter(status__in=OPEN_STEP_STATUSES)
            .select_related("recipient", "sender")
            .order_by("sequence")
            .first()
        )


class DocumentVersion(WriteOnceModel):
    """
    The document's bytes at one point in its life.

    Version 1 is the original as uploaded and is kept for good. Each signature
    produces the next version as an incremental update of the one before, so
    every earlier signature stays verifiable inside it. The SHA-256 digest is
    taken when the file is written and checked every time it is read back.
    """

    class Kind(models.TextChoices):
        ORIGINAL = "ORIGINAL", "Original upload"
        SIGNED = "SIGNED", "Signed"

    document = models.ForeignKey(
        EsiraDocument, on_delete=models.PROTECT, related_name="versions",
    )
    number = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    file = models.FileField(
        upload_to="esira/%Y/%m/", storage=protected_storage, max_length=255,
    )
    sha256 = models.CharField("SHA-256", max_length=64)
    size = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "e-SIRA document version"
        ordering = ("document", "number")
        constraints = [
            models.UniqueConstraint(
                fields=("document", "number"), name="esira_version_unique_number",
            ),
        ]

    def __str__(self):
        return f"{self.document.reference_no} v{self.number} ({self.get_kind_display()})"

    def read_verified(self):
        """
        The stored bytes, after proving they are the bytes that were written.

        Raises `IntegrityError` if the file on disk no longer matches its
        recorded digest - someone or something changed it outside the system.
        """
        with self.file.open("rb") as handle:
            data = handle.read()
        if sha256_hex(data) != self.sha256:
            raise FileIntegrityError(self)
        return data


class FileIntegrityError(Exception):
    def __init__(self, version):
        self.version = version
        super().__init__(
            f"The stored file for {version} does not match its recorded digest."
        )


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


class SignatureBox(models.Model):
    """
    Where a named person's signature is to appear.

    Coordinates are fractions (0-1) of the page as it is displayed - origin at
    the top left, after the page's own rotation - so they do not depend on the
    zoom level the box was drawn at. `esira.pdf.box_to_pdf_rect` turns them
    into PDF user space at the moment of signing.

    A box is only ever a placement. It becomes a signature when, and only
    when, `signature` is set by a real signing operation; after that it is
    locked.
    """

    document = models.ForeignKey(
        EsiraDocument, on_delete=models.CASCADE, related_name="boxes",
    )
    signer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="esira_signature_boxes",
    )
    page = models.PositiveIntegerField(help_text="1-based page number.")
    x = models.FloatField()
    y = models.FloatField()
    width = models.FloatField()
    height = models.FloatField()

    signature = models.ForeignKey(
        "DigitalSignature", on_delete=models.PROTECT, null=True, blank=True,
        related_name="boxes",
    )
    field_name = models.CharField(max_length=60, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "signature box"
        verbose_name_plural = "signature boxes"
        ordering = ("page", "y", "x", "pk")

    def __str__(self):
        return f"Box on page {self.page} for {self.signer}"

    @property
    def is_applied(self):
        return self.signature_id is not None

    def as_dict(self):
        return {
            "id": self.pk,
            "page": self.page,
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "width": round(self.width, 6),
            "height": round(self.height, 6),
            "signer": self.signer_id,
            "signer_name": self.signer.get_display_name(),
            "applied": self.is_applied,
        }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class RoutingStep(models.Model):
    """
    One recipient's turn with the document.

    Steps run in `sequence` order: one step is open at a time and the next is
    only sent when it is done. The timestamps are the routing slip -
    `routed_at` when it reached the recipient, `received_at` when they first
    opened it, `acted_at` when they signed, approved or rejected it.
    """

    document = models.ForeignKey(
        EsiraDocument, on_delete=models.CASCADE, related_name="steps",
    )
    sequence = models.PositiveIntegerField()
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="esira_steps",
    )
    action = models.CharField(max_length=12, choices=StepAction.choices)
    purpose = models.CharField(
        "purpose / action required", max_length=255, blank=True,
    )
    status = models.CharField(
        max_length=12, choices=StepStatus.choices,
        default=StepStatus.QUEUED, db_index=True,
    )
    due_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    routed_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    remarks = models.TextField(blank=True)

    class Meta:
        verbose_name = "routing step"
        ordering = ("document", "sequence")
        indexes = [models.Index(fields=("recipient", "status"))]

    def __str__(self):
        return (
            f"{self.document.reference_no} #{self.sequence}: "
            f"{self.get_action_display()} by {self.recipient}"
        )

    @property
    def is_open(self):
        return self.status in OPEN_STEP_STATUSES

    @property
    def is_done(self):
        return self.status in DONE_STEP_STATUSES

    @property
    def is_signature(self):
        return self.action == StepAction.SIGN

    @property
    def status_tone(self):
        return STEP_TONES.get(self.status, "neutral")


# ---------------------------------------------------------------------------
# Certificates and signatures
# ---------------------------------------------------------------------------


class SigningCertificate(models.Model):
    """
    A PNPKI certificate an employee has registered as theirs.

    Only the public certificate is kept - never a private key. Registering a
    certificate does not authorise it: an administrator checks that it was
    issued to this employee and marks it verified. Signing then requires the
    signer to present the matching private key, and the certificate to be
    verified, in date and (outside development) chained to the PNPKI roots.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Awaiting verification"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"
        REVOKED = "REVOKED", "Revoked"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="esira_certificates",
    )
    certificate_pem = models.TextField(help_text="The public certificate, PEM encoded.")
    subject = models.CharField(max_length=500)
    subject_common_name = models.CharField(max_length=255, blank=True)
    subject_email = models.CharField(max_length=255, blank=True)
    issuer = models.CharField(max_length=500)
    serial_number = models.CharField(max_length=80)
    fingerprint_sha256 = models.CharField("SHA-256 fingerprint", max_length=64, unique=True)
    not_before = models.DateTimeField()
    not_after = models.DateTimeField()

    # Whether the certificate chained to a configured PNPKI root when it was
    # last checked, and what the check said.
    chain_trusted = models.BooleanField(default=False)
    chain_note = models.CharField(max_length=500, blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_remarks = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "signing certificate"
        ordering = ("-submitted_at",)

    def __str__(self):
        return f"{self.subject_common_name or self.subject} ({self.get_status_display()})"

    @property
    def is_expired(self):
        return self.not_after <= timezone.now()

    @property
    def is_not_yet_valid(self):
        return self.not_before > timezone.now()

    @property
    def is_usable(self):
        return (
            self.status == self.Status.VERIFIED
            and not self.is_expired
            and not self.is_not_yet_valid
        )

    @property
    def status_tone(self):
        if self.status == self.Status.VERIFIED and self.is_expired:
            return "overdue"
        return {
            self.Status.PENDING: "pending",
            self.Status.VERIFIED: "verified",
            self.Status.REJECTED: "rejected",
            self.Status.REVOKED: "cancelled",
        }.get(self.status, "neutral")

    @property
    def fingerprint_display(self):
        f = self.fingerprint_sha256.upper()
        return ":".join(f[i:i + 2] for i in range(0, len(f), 2))


class DigitalSignature(WriteOnceModel):
    """
    A cryptographic signature applied to the document.

    One row per signing act. The certificate details are copied in rather
    than only referenced, so the record says what signed the document even if
    the registered certificate is later revoked.
    """

    document = models.ForeignKey(
        EsiraDocument, on_delete=models.PROTECT, related_name="signatures",
    )
    step = models.OneToOneField(
        RoutingStep, on_delete=models.PROTECT, related_name="signature",
    )
    signer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="esira_signatures",
    )
    source_version = models.ForeignKey(
        DocumentVersion, on_delete=models.PROTECT, related_name="+",
    )
    result_version = models.OneToOneField(
        DocumentVersion, on_delete=models.PROTECT, related_name="signature",
    )
    certificate = models.ForeignKey(
        SigningCertificate, on_delete=models.PROTECT, related_name="signatures",
    )

    backend = models.CharField(max_length=20)
    certificate_subject = models.CharField(max_length=500)
    certificate_issuer = models.CharField(max_length=500)
    certificate_serial = models.CharField(max_length=80)
    certificate_fingerprint = models.CharField(max_length=64)
    certificate_not_after = models.DateTimeField()
    chain_trusted = models.BooleanField(
        help_text="Whether the certificate chained to a configured PNPKI root.",
    )
    trust_note = models.CharField(max_length=500, blank=True)

    reason = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    field_names = models.JSONField(default=list)
    timestamped = models.BooleanField(default=False)
    signed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "digital signature"
        ordering = ("signed_at", "pk")

    def __str__(self):
        return f"{self.document.reference_no} signed by {self.signer}"

    @property
    def box_count(self):
        return len(self.field_names or [])


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class AuditAction(models.TextChoices):
    UPLOADED = "UPLOADED", "Document uploaded"
    VIEWED = "VIEWED", "Document viewed"
    DOWNLOADED = "DOWNLOADED", "Document downloaded"
    BOX_ADDED = "BOX_ADDED", "Signature box added"
    BOX_MODIFIED = "BOX_MODIFIED", "Signature box modified"
    BOX_REMOVED = "BOX_REMOVED", "Signature box removed"
    SIGNED = "SIGNED", "Document signed"
    SIGN_FAILED = "SIGN_FAILED", "Signing refused"
    ROUTED = "ROUTED", "Document routed"
    RECEIVED = "RECEIVED", "Document received"
    APPROVED = "APPROVED", "Document approved"
    REVIEWED = "REVIEWED", "Document reviewed"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Document acknowledged"
    FORWARDED = "FORWARDED", "Document forwarded"
    REJECTED = "REJECTED", "Document rejected"
    COMPLETED = "COMPLETED", "Document completed"
    CANCELLED = "CANCELLED", "Document cancelled"
    SIGNATURES_VERIFIED = "SIGNATURES_VERIFIED", "Signatures verified"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE", "File integrity check failed"
    CERT_REGISTERED = "CERT_REGISTERED", "Certificate registered"
    CERT_VERIFIED = "CERT_VERIFIED", "Certificate verified"
    CERT_REJECTED = "CERT_REJECTED", "Certificate rejected"
    CERT_REVOKED = "CERT_REVOKED", "Certificate revoked"


AUDIT_TONES = {
    AuditAction.UPLOADED: "new",
    AuditAction.VIEWED: "archived",
    AuditAction.DOWNLOADED: "archived",
    AuditAction.BOX_ADDED: "in_progress",
    AuditAction.BOX_MODIFIED: "in_progress",
    AuditAction.BOX_REMOVED: "in_progress",
    AuditAction.SIGNED: "completed",
    AuditAction.SIGN_FAILED: "failed",
    AuditAction.ROUTED: "in_progress",
    AuditAction.RECEIVED: "received",
    AuditAction.APPROVED: "approved",
    AuditAction.REVIEWED: "reviewed",
    AuditAction.ACKNOWLEDGED: "acknowledged",
    AuditAction.FORWARDED: "in_progress",
    AuditAction.REJECTED: "rejected",
    AuditAction.COMPLETED: "completed",
    AuditAction.CANCELLED: "cancelled",
    AuditAction.SIGNATURES_VERIFIED: "verified",
    AuditAction.INTEGRITY_FAILURE: "critical",
    AuditAction.CERT_REGISTERED: "submitted",
    AuditAction.CERT_VERIFIED: "verified",
    AuditAction.CERT_REJECTED: "rejected",
    AuditAction.CERT_REVOKED: "cancelled",
}


class AuditEntry(WriteOnceModel):
    """
    One action in e-SIRA, in the office's words.

    The actor's name and role and the document's reference are copied in, so
    the entry still reads correctly if an account is renamed or deactivated.
    The most significant actions are also mirrored to the system-wide audit
    log (see esira/audit.py), so an administrator reading that log sees them
    beside everything else.
    """

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    document = models.ForeignKey(
        EsiraDocument, on_delete=models.PROTECT, null=True, blank=True,
        related_name="audit_entries",
    )
    document_reference = models.CharField(max_length=30, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    actor_label = models.CharField(max_length=150)
    actor_role = models.CharField(max_length=40, blank=True)
    action = models.CharField(max_length=20, choices=AuditAction.choices, db_index=True)
    detail = models.CharField(max_length=500, blank=True)
    version_number = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "e-SIRA audit entry"
        verbose_name_plural = "e-SIRA audit entries"
        ordering = ("-timestamp", "-id")
        indexes = [models.Index(fields=("document", "-timestamp"))]

    def __str__(self):
        return f"{self.actor_label}: {self.get_action_display()} {self.document_reference}".strip()

    @property
    def status_tone(self):
        return AUDIT_TONES.get(self.action, "neutral")
