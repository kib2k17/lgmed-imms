"""
The Division's document register, from the moment a document is received or
drafted until it is archived and, eventually, disposed of under authority.

Every document the Division receives, creates, submits or processes is
recorded here, whatever its type. Five tables, because five different things
are being remembered:

  DocumentType      what kind of document it is, and how long it must be kept
  Document          the document, its ownership, and where it currently stands
  DocumentVersion   every file the document has ever had, never overwritten
  DocumentEvent     the trail - who did what to it, and when
  DisposalAuthority the written authority a permanent disposal was made under

The rules the module exists to enforce, and which a shared folder cannot:

  * A document always has an owner. Nothing is filed anonymously.
  * A file is never replaced. Uploading a revision creates a new version and
    keeps the old one, with the reason it was superseded.
  * Nothing is deleted by an ordinary user. A document leaves circulation by
    being archived, and leaves the archive only by an authorised disposal that
    is itself recorded.
  * Every consequential act - viewing, downloading, editing, assigning,
    archiving, restoring, disposing - is written to the document's own trail.
"""

import os
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.db.models import Max, Q
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel

# How far ahead the dashboard looks when it asks "what is about to fall due
# for retention review?". Ninety days is a quarter: long enough that the
# records officer can schedule the review rather than be ambushed by it.
RETENTION_WARNING_DAYS = 90


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class RetentionAction(models.TextChoices):
    """What is to become of a document once its retention period has run."""

    REVIEW = "REVIEW", "Review before disposal"
    DISPOSE = "DISPOSE", "Dispose"
    PERMANENT = "PERMANENT", "Preserve permanently"


class DocumentType(models.Model):
    """
    Reference list of document types, editable in System Settings.

    The retention period lives here rather than on each document because that
    is how a records schedule actually works: an office decides once that
    memoranda are kept for five years, not five years at a time.
    """

    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(
        max_length=12,
        blank=True,
        help_text="Short code used in control numbers, e.g. MEMO.",
    )
    description = models.TextField(blank=True)

    retention_years = models.PositiveSmallIntegerField(
        "retention period (years)",
        null=True,
        blank=True,
        help_text=(
            "How long a completed document of this type is kept before it "
            "falls due for retention review. Leave blank if no period has "
            "been set for this type."
        ),
    )
    retention_action = models.CharField(
        "action at end of retention",
        max_length=10,
        choices=RetentionAction.choices,
        default=RetentionAction.REVIEW,
        help_text="What the records officer should do when the period runs out.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    @property
    def retention_label(self):
        if self.retention_years is None:
            return "No period set"
        years = self.retention_years
        if years == 0:
            return f"On completion - {self.get_retention_action_display().lower()}"
        return (
            f"{years} year{'s' if years != 1 else ''} - "
            f"{self.get_retention_action_display().lower()}"
        )


class ControlNumberSequence(models.Model):
    """
    The last control number issued for a year.

    Kept as its own row rather than derived from `MAX(reference_number)`,
    because a maximum is only as durable as the record holding it: delete the
    newest document and the next registration is handed a number that has
    already been used. A register that issues the same control number twice is
    worse than one with gaps in it, so the counter is stored and only ever
    counts up.
    """

    year = models.PositiveIntegerField(primary_key=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "control number sequence"
        ordering = ("-year",)

    def __str__(self):
        return f"{self.year}: {self.last_number} issued"


class DisposalAuthority(models.Model):
    """
    A written authority under which documents may be permanently disposed of.

    Disposal is the one irreversible act in the module, so it may not rest on
    a checkbox. The authority - a board resolution, an approved records
    disposal schedule - is recorded first and then cited by each disposal made
    under it, which is what an auditor will ask to see.
    """

    reference = models.CharField(
        max_length=120,
        unique=True,
        help_text="e.g. NAP-RDS-2026-014, or the board resolution number.",
    )
    title = models.CharField(max_length=255)
    approved_on = models.DateField()
    approved_by = models.CharField(
        max_length=200,
        help_text="The officer or body that granted the authority.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "disposal authority"
        verbose_name_plural = "disposal authorities"
        ordering = ("-approved_on", "reference")

    def __str__(self):
        return f"{self.reference} - {self.title}"


# ---------------------------------------------------------------------------
# The lifecycle
# ---------------------------------------------------------------------------


class DocumentStatus(models.TextChoices):
    """
    Where a document stands.

    The order of declaration is the order of the lifecycle, and
    `LIFECYCLE_ORDER` below depends on it.
    """

    DRAFT = "DRAFT", "Draft"
    RECEIVED = "RECEIVED", "Received"
    FOR_REVIEW = "FOR_REVIEW", "For review"
    FOR_ASSIGNMENT = "FOR_ASSIGNMENT", "For assignment"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    FOR_APPROVAL = "FOR_APPROVAL", "For approval"
    COMPLETED = "COMPLETED", "Completed"
    ARCHIVED = "ARCHIVED", "Archived"
    CANCELLED = "CANCELLED", "Cancelled"


# The stages shown on a document's progress indicator, in order. Cancellation
# and archiving are ends rather than stages, and are handled separately.
LIFECYCLE_ORDER = (
    DocumentStatus.DRAFT,
    DocumentStatus.RECEIVED,
    DocumentStatus.FOR_REVIEW,
    DocumentStatus.FOR_ASSIGNMENT,
    DocumentStatus.ASSIGNED,
    DocumentStatus.IN_PROGRESS,
    DocumentStatus.FOR_APPROVAL,
    DocumentStatus.COMPLETED,
)

# Still in circulation: someone is expected to do something about it.
OPEN_STATUSES = tuple(
    value
    for value in DocumentStatus.values
    if value
    not in (
        DocumentStatus.COMPLETED,
        DocumentStatus.ARCHIVED,
        DocumentStatus.CANCELLED,
    )
)

# Out of circulation, whether finished, filed or abandoned.
CLOSED_STATUSES = (
    DocumentStatus.COMPLETED,
    DocumentStatus.ARCHIVED,
    DocumentStatus.CANCELLED,
)

# A document may only be offered on the public website once the Division has
# finished with it. Stated once here because several other modules ask.
PUBLIC_STATUSES = (DocumentStatus.COMPLETED,)


class RetentionDisposition(models.TextChoices):
    """The records officer's decision about a document's long-term fate."""

    ACTIVE = "ACTIVE", "Within retention period"
    FOR_REVIEW = "FOR_REVIEW", "For retention review"
    FOR_DISPOSAL = "FOR_DISPOSAL", "For disposal"
    PERMANENT = "PERMANENT", "Permanent preservation"
    DISPOSED = "DISPOSED", "Disposed"


class EventType(models.TextChoices):
    """Everything the trail can record. See `DocumentEvent`."""

    REGISTERED = "REGISTERED", "Registered"
    UPLOADED = "UPLOADED", "File uploaded"
    VIEWED = "VIEWED", "Viewed"
    DOWNLOADED = "DOWNLOADED", "Downloaded"
    EDITED = "EDITED", "Details edited"
    ASSIGNED = "ASSIGNED", "Assigned"
    REASSIGNED = "REASSIGNED", "Reassigned"
    STATUS_CHANGED = "STATUS_CHANGED", "Status changed"
    VERSION_UPLOADED = "VERSION_UPLOADED", "New version uploaded"
    APPROVED = "APPROVED", "Approved"
    CANCELLED = "CANCELLED", "Cancelled"
    RETENTION_SET = "RETENTION_SET", "Retention set"
    ARCHIVED = "ARCHIVED", "Archived"
    RESTORED = "RESTORED", "Restored from archive"
    DISPOSED = "DISPOSED", "Disposed"


# ---------------------------------------------------------------------------
# File storage
# ---------------------------------------------------------------------------

# What may be uploaded. Enforced in `documents.forms`, stated here so the
# model, the form and the help text cannot disagree about it.
ALLOWED_EXTENSIONS = (
    "pdf",
    "doc", "docx",
    "xls", "xlsx", "csv",
    "ppt", "pptx",
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff",
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def document_path(instance, filename):
    return f"documents/{instance.year}/{filename}"


def version_path(instance, filename):
    return (
        f"documents/versions/{instance.document_id}/"
        f"v{instance.version_number}/{filename}"
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentQuerySet(models.QuerySet):
    """The questions the register, the dashboard and the filters actually ask."""

    def open(self):
        return self.filter(status__in=OPEN_STATUSES)

    def completed(self):
        return self.filter(status=DocumentStatus.COMPLETED)

    def archived(self):
        return self.filter(status=DocumentStatus.ARCHIVED)

    def live(self):
        """Everything except the archive."""
        return self.exclude(status=DocumentStatus.ARCHIVED)

    def public(self):
        """Documents cleared for the public website."""
        return self.filter(is_public=True, status__in=PUBLIC_STATUSES)

    def owned_by(self, user):
        return self.filter(owner=user)

    def assigned_to(self, user):
        return self.filter(assigned_to=user)

    def involving(self, user):
        """Anything this person is answerable for."""
        return self.filter(
            Q(owner=user) | Q(assigned_to=user) | Q(created_by=user)
        ).distinct()

    def overdue(self, today=None):
        return self.open().filter(
            due_date__isnull=False, due_date__lt=today or timezone.localdate()
        )

    def retention_due(self, today=None):
        """Past the end of its retention period and not yet dealt with."""
        return self.filter(
            retention_until__isnull=False,
            retention_until__lte=today or timezone.localdate(),
        ).exclude(
            retention_disposition__in=(
                RetentionDisposition.PERMANENT,
                RetentionDisposition.DISPOSED,
            )
        )

    def retention_approaching(self, days=RETENTION_WARNING_DAYS, today=None):
        """Falling due within `days`, so the review can be scheduled."""
        today = today or timezone.localdate()
        return self.filter(
            retention_until__isnull=False,
            retention_until__gt=today,
            retention_until__lte=today + timedelta(days=days),
        ).exclude(
            retention_disposition__in=(
                RetentionDisposition.PERMANENT,
                RetentionDisposition.DISPOSED,
            )
        )

    def for_disposal(self):
        return self.filter(retention_disposition=RetentionDisposition.FOR_DISPOSAL)

    def visible_to(self, user):
        """
        The register as this user may see it.

        Archived documents are restricted: they are out of circulation, and
        continued general access to them is how a "closed" record quietly
        stays open. The people who archive and dispose may read the archive,
        and so may the document's own owner and focal person - restricting a
        record from the person answerable for it helps nobody.
        """
        if getattr(user, "can_archive_documents", False):
            return self
        if not getattr(user, "is_authenticated", False):
            return self.none()
        return self.exclude(
            Q(status=DocumentStatus.ARCHIVED)
            & ~Q(Q(owner=user) | Q(assigned_to=user) | Q(created_by=user))
        )


class Document(TimeStampedModel):
    """One document held by the Division, and its progress through the office."""

    # -- identity ---------------------------------------------------------
    title = models.CharField("document title", max_length=255)
    reference_number = models.CharField(
        "document / reference / control number",
        max_length=60,
        unique=True,
        db_index=True,
        blank=True,
        help_text=(
            "The office's control number for this document. Left blank, the "
            "system issues the next one for the year."
        ),
    )
    document_type = models.ForeignKey(
        DocumentType, on_delete=models.PROTECT, related_name="documents"
    )
    subject = models.CharField(
        max_length=255,
        blank=True,
        help_text="What the document is about, in one line.",
    )
    sender = models.CharField(
        "sender / source",
        max_length=200,
        blank=True,
        help_text="The office, agency, LGU or person the document came from.",
    )
    description = models.TextField(blank=True)
    remarks = models.TextField(blank=True)

    # -- dates ------------------------------------------------------------
    date_received = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "When the document arrived at the Division. Leave blank for a "
            "document the Division itself created."
        ),
    )
    date_created = models.DateField(
        "date of document",
        null=True,
        blank=True,
        db_index=True,
        help_text="The date written on the document itself.",
    )
    due_date = models.DateField(
        "action due date",
        null=True,
        blank=True,
        help_text="The date by which the action should be completed.",
    )
    year = models.PositiveIntegerField(db_index=True)

    # -- where it sits in the office --------------------------------------
    office = models.CharField(
        "office / division",
        max_length=150,
        default="Local Government Monitoring and Evaluation Division",
    )
    unit = models.ForeignKey(
        "accounts.Section",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        verbose_name="division / unit",
        help_text="The unit responsible for this document.",
    )

    # -- ownership --------------------------------------------------------
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="documents_owned",
        verbose_name="owner / responsible personnel",
        help_text=(
            "The person answerable for this document. Defaults to whoever "
            "registers it."
        ),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents_assigned",
        verbose_name="assigned personnel / focal person",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    assignment_remarks = models.TextField(
        "assignment remarks / instructions", blank=True
    )

    # -- the file ---------------------------------------------------------
    file = models.FileField(
        "document file",
        upload_to=document_path,
        blank=True,
        help_text=(
            "PDF, Word, Excel, PowerPoint or an image. The current version - "
            "every earlier one is kept."
        ),
    )

    # -- state ------------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    is_public = models.BooleanField(
        "Available on the public website",
        default=False,
        help_text="Only a completed document may be offered publicly.",
    )

    # -- retention and archiving -------------------------------------------
    retention_until = models.DateField(
        "retention period ends",
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Worked out from the document type's retention period when the "
            "document is completed. May be overridden."
        ),
    )
    retention_disposition = models.CharField(
        "retention decision",
        max_length=20,
        choices=RetentionDisposition.choices,
        default=RetentionDisposition.ACTIVE,
        db_index=True,
    )
    retention_notes = models.TextField(blank=True)
    retention_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    retention_reviewed_at = models.DateTimeField(null=True, blank=True)

    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    archive_reason = models.TextField(blank=True)

    disposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    disposed_at = models.DateTimeField(null=True, blank=True)
    disposal_authority = models.ForeignKey(
        DisposalAuthority,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="disposals",
    )
    disposal_notes = models.TextField(blank=True)

    # Set when the entry mirrors an incoming document. Its lifecycle is then
    # driven from Incoming and Outgoing Monitoring (see incoming/register.py),
    # and only the records officer's archive, retention and disposal act on it
    # here - a register moved from two places at once soon says two things.
    incoming = models.OneToOneField(
        "incoming.IncomingDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="register_entry",
        verbose_name="incoming document",
    )
    # Set when the entry mirrors a row of the outgoing register that answers
    # no incoming document (those are captured under the incoming entry).
    outgoing = models.OneToOneField(
        "outgoing.OutgoingDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="register_entry",
        verbose_name="outgoing communication",
    )

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ("-year", "-created_at")
        indexes = [
            models.Index(fields=("year", "status")),
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("owner", "status")),
            models.Index(fields=("assigned_to", "status")),
            models.Index(fields=("retention_disposition", "retention_until")),
        ]

    def __str__(self):
        if self.reference_number:
            return f"{self.reference_number} - {self.title}"
        return self.title

    def get_absolute_url(self):
        return reverse("documents:detail", args=[self.pk])

    # -- control numbers ---------------------------------------------------

    def save(self, *args, **kwargs):
        if not self.year:
            reference = self.date_received or self.date_created
            self.year = (reference or timezone.localdate()).year
        if not self.reference_number:
            self.reference_number = self.next_reference_number(self.year)
        super().save(*args, **kwargs)

    @classmethod
    def next_reference_number(cls, year, prefix="LGMED"):
        """
        Issue the next control number for a year, as ``LGMED-2026-0042``.

        Taken from a stored counter rather than from the highest number
        currently in the table, so a number is never reused after a record is
        removed. See `ControlNumberSequence`.
        """
        stem = f"{prefix}-{year}-"
        with transaction.atomic():
            sequence = (
                ControlNumberSequence.objects.select_for_update()
                .filter(pk=year)
                .first()
            )
            if sequence is None:
                # First registration of the year. Start above anything the
                # register already holds, so a counter added to a system with
                # documents in it does not reissue their numbers.
                sequence = ControlNumberSequence(
                    year=year, last_number=cls._highest_issued(stem)
                )
            sequence.last_number += 1
            sequence.save()
        return f"{stem}{sequence.last_number:04d}"

    @classmethod
    def _highest_issued(cls, stem):
        """The largest sequence already present under a control-number stem."""
        highest = 0
        numbers = cls.objects.filter(
            reference_number__startswith=stem
        ).values_list("reference_number", flat=True)
        for number in numbers:
            tail = number[len(stem):]
            if tail.isdigit():
                highest = max(highest, int(tail))
        return highest

    # -- state -------------------------------------------------------------

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def is_completed(self):
        return self.status == DocumentStatus.COMPLETED

    @property
    def is_archived(self):
        return self.status == DocumentStatus.ARCHIVED

    @property
    def is_cancelled(self):
        return self.status == DocumentStatus.CANCELLED

    @property
    def is_disposed(self):
        return self.retention_disposition == RetentionDisposition.DISPOSED

    @property
    def is_assigned(self):
        return self.assigned_to_id is not None

    @property
    def is_synced(self):
        """Mirrors Incoming or Outgoing Monitoring, which drive its lifecycle."""
        return self.incoming_id is not None or self.outgoing_id is not None

    @property
    def source(self):
        if self.incoming_id:
            return "incoming"
        if self.outgoing_id:
            return "outgoing"
        return "direct"

    @property
    def source_label(self):
        return {
            "incoming": "Incoming Monitoring",
            "outgoing": "Outgoing Monitoring",
            "direct": "Registered here",
        }[self.source]

    @property
    def is_overdue(self):
        return bool(
            self.due_date and self.is_open and self.due_date < timezone.localdate()
        )

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days

    @property
    def display_status(self):
        """Overdue outranks the stored status wherever the record is shown."""
        return "overdue" if self.is_overdue else self.status

    @property
    def display_status_label(self):
        if self.is_overdue:
            return f"Overdue - {self.get_status_display()}"
        return self.get_status_display()

    @property
    def is_available_publicly(self):
        return self.is_public and self.status in PUBLIC_STATUSES

    # -- retention ----------------------------------------------------------

    @property
    def retention_days_remaining(self):
        if not self.retention_until:
            return None
        return (self.retention_until - timezone.localdate()).days

    @property
    def is_retention_settled(self):
        """Permanently preserved or already disposed of: nothing left to decide."""
        return self.retention_disposition in (
            RetentionDisposition.PERMANENT,
            RetentionDisposition.DISPOSED,
        )

    @property
    def is_retention_due(self):
        days = self.retention_days_remaining
        return days is not None and days <= 0 and not self.is_retention_settled

    @property
    def is_retention_approaching(self):
        days = self.retention_days_remaining
        return (
            days is not None
            and 0 < days <= RETENTION_WARNING_DAYS
            and not self.is_retention_settled
        )

    @property
    def retention_summary(self):
        """One line for the record page and the retention register."""
        if self.is_disposed:
            return "Disposed"
        if self.retention_disposition == RetentionDisposition.PERMANENT:
            return "Permanent preservation"
        if not self.retention_until:
            return "No retention period set"
        days = self.retention_days_remaining
        if days <= 0:
            return f"Due since {self.retention_until:%d %b %Y}"
        if days <= RETENTION_WARNING_DAYS:
            return f"Due {self.retention_until:%d %b %Y} - in {days} days"
        return f"Retained until {self.retention_until:%d %b %Y}"

    def computed_retention_until(self, from_date=None):
        """
        The end of the retention period implied by the document's type.

        Returns None where the type carries no period, which is not the same
        as a period of zero - "nobody has decided yet" must not silently
        become "dispose of it today".
        """
        years = self.document_type.retention_years
        if years is None:
            return None
        start = from_date or timezone.localdate()
        try:
            return start.replace(year=start.year + years)
        except ValueError:  # 29 February in a year that has no 29 February
            return start.replace(month=2, day=28, year=start.year + years)

    # -- who may do what ----------------------------------------------------

    def is_responsible(self, user):
        """The owner, the focal person, or whoever registered it."""
        pk = getattr(user, "pk", None)
        if pk is None:
            return False
        return pk in (self.owner_id, self.assigned_to_id, self.created_by_id)

    def may_be_viewed_by(self, user):
        """
        Archived documents are restricted; everything else is readable by any
        signed-in account, which is what a register is for.
        """
        if not getattr(user, "is_authenticated", False):
            return False
        if not self.is_archived:
            return bool(getattr(user, "can_view", False))
        return bool(
            getattr(user, "can_archive_documents", False) or self.is_responsible(user)
        )

    def may_be_downloaded_by(self, user):
        """A document with no file cannot be downloaded, disposed or not."""
        if self.is_disposed or not self.file:
            return False
        return self.may_be_viewed_by(user)

    def may_be_edited_by(self, user):
        """
        Details may be corrected by the people answerable for the document.

        An archived or disposed document is not edited at all: restoring it is
        the way back, and that is a decision someone has to take and sign.
        """
        if not getattr(user, "can_encode", False):
            return False
        if self.is_archived or self.is_disposed or self.is_synced:
            return False
        if getattr(user, "can_archive_documents", False):
            return True
        return self.is_responsible(user)

    def may_upload_version_by(self, user):
        """Superseding the file is an edit, and follows the same rule."""
        return self.may_be_edited_by(user)

    def may_be_assigned_by(self, user):
        if self.is_archived or self.is_disposed or self.is_cancelled:
            return False
        if self.is_synced:
            return False
        return bool(getattr(user, "can_assign_documents", False))

    def may_be_archived_by(self, user):
        if self.is_archived or self.is_disposed:
            return False
        if self.status not in (DocumentStatus.COMPLETED, DocumentStatus.CANCELLED):
            return False
        return bool(getattr(user, "can_archive_documents", False))

    def may_be_restored_by(self, user):
        if not self.is_archived or self.is_disposed:
            return False
        return bool(getattr(user, "can_archive_documents", False))

    def may_be_disposed_by(self, user):
        """
        Disposal needs three things at once: the capability, an archived
        document, and a retention decision that actually says to dispose of it.
        """
        if self.is_disposed or not self.is_archived:
            return False
        if self.retention_disposition != RetentionDisposition.FOR_DISPOSAL:
            return False
        return bool(getattr(user, "can_dispose_documents", False))

    def require_viewable_by(self, user):
        if not self.may_be_viewed_by(user):
            raise PermissionDenied(
                "This document is archived. Ask the records officer for access."
            )

    # -- versions -----------------------------------------------------------

    @property
    def current_version(self):
        return self.versions.first()

    @property
    def version_count(self):
        return self.versions.count()

    def next_version_number(self):
        highest = self.versions.aggregate(top=Max("version_number"))["top"]
        return (highest or 0) + 1

    def _version_actor(self, user):
        return user if getattr(user, "is_authenticated", False) else None

    @transaction.atomic
    def add_version(self, uploaded_file, *, user, reason="", make_current=True):
        """
        Store a newly uploaded file as the next version.

        The previous version is never touched: `DocumentVersion` rows are
        written once and only ever read afterwards. `Document.file` is then
        pointed at the *same stored file* rather than given a copy of it -
        two rows referring to one file on disk, not two files that can drift
        apart and double the storage every revision.
        """
        version = DocumentVersion.objects.create(
            document=self,
            version_number=self.next_version_number(),
            file=uploaded_file,
            uploaded_by=self._version_actor(user),
            reason=reason,
        )
        if make_current:
            self.file.name = version.file.name
            self.save(update_fields=["file", "updated_at"])
        return version

    @transaction.atomic
    def adopt_current_file(self, *, user, reason=""):
        """
        Record the file already on this document as its next version.

        Used where a form has just saved the upload itself. The version row is
        pointed at the file that is already stored rather than being handed the
        upload again, which would write a second copy and leave the first
        orphaned.
        """
        if not self.file:
            return None
        version = DocumentVersion(
            document=self,
            version_number=self.next_version_number(),
            uploaded_by=self._version_actor(user),
            reason=reason,
        )
        version.file.name = self.file.name
        version.save()
        return version

    # -- presentation --------------------------------------------------------

    @property
    def file_type(self):
        if not self.file:
            return ""
        return os.path.splitext(self.file.name)[1].lstrip(".").upper() or "FILE"

    @property
    def file_size(self):
        try:
            return self.file.size
        except (ValueError, OSError):
            return 0

    @property
    def file_name(self):
        return os.path.basename(self.file.name) if self.file else ""

    @property
    def owner_label(self):
        return self.owner.get_display_name() if self.owner_id else "Not recorded"

    @property
    def assignee_label(self):
        return (
            self.assigned_to.get_display_name()
            if self.assigned_to_id
            else "Not assigned"
        )

    @property
    def unit_label(self):
        return self.unit.name if self.unit_id else (self.office or "Not recorded")

    @property
    def workflow(self):
        """Ordered stages for the record's progress indicator."""
        if self.is_cancelled:
            return [{"label": "Cancelled", "state": "cancelled"}]

        labels = {
            DocumentStatus.DRAFT: "Draft",
            DocumentStatus.RECEIVED: "Registered",
            DocumentStatus.FOR_REVIEW: "Reviewed",
            DocumentStatus.FOR_ASSIGNMENT: "For assignment",
            DocumentStatus.ASSIGNED: "Assigned",
            DocumentStatus.IN_PROGRESS: "Processing",
            DocumentStatus.FOR_APPROVAL: "Approval",
            DocumentStatus.COMPLETED: "Completed",
        }
        # An archived document has been through the whole journey; it is shown
        # as complete with the archive appended, not as a document stuck at a
        # stage it left months ago.
        effective = DocumentStatus.COMPLETED if self.is_archived else self.status
        try:
            current = LIFECYCLE_ORDER.index(effective)
        except ValueError:
            current = 0
        finished = effective == DocumentStatus.COMPLETED

        stages = [
            {
                "label": labels[value],
                "state": (
                    "done"
                    if index < current or (finished and index == current)
                    else "current" if index == current
                    else "upcoming"
                ),
            }
            for index, value in enumerate(LIFECYCLE_ORDER)
        ]
        if self.is_archived:
            stages.append(
                {
                    "label": "Disposed" if self.is_disposed else "Archived",
                    "state": "done",
                }
            )
        return stages


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


class DocumentVersion(models.Model):
    """
    One file a document has had, and why it was superseded.

    Rows here are written once. There is no edit or delete path in the
    interface, because the point of a version history is that it cannot be
    tidied up after the fact.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    file = models.FileField(upload_to=version_path)
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reason = models.TextField(
        "reason for revision",
        blank=True,
        help_text="Why this version replaced the one before it.",
    )

    class Meta:
        verbose_name = "document version"
        ordering = ("-version_number",)
        constraints = [
            models.UniqueConstraint(
                fields=("document", "version_number"),
                name="unique_version_per_document",
            )
        ]

    def __str__(self):
        return f"{self.document.reference_number} v{self.version_number}"

    def get_absolute_url(self):
        return reverse("documents:version_download", args=[self.document_id, self.pk])

    @property
    def label(self):
        return f"Version {self.version_number}"

    @property
    def file_name(self):
        return os.path.basename(self.file.name) if self.file else ""

    @property
    def file_type(self):
        if not self.file:
            return ""
        return os.path.splitext(self.file.name)[1].lstrip(".").upper() or "FILE"

    @property
    def file_size(self):
        try:
            return self.file.size
        except (ValueError, OSError):
            return 0

    @property
    def uploader_label(self):
        return self.uploaded_by.get_display_name() if self.uploaded_by_id else "System"


# ---------------------------------------------------------------------------
# Supporting files captured from Incoming and Outgoing Monitoring
# ---------------------------------------------------------------------------


class FileSource(models.TextChoices):
    UPDATE = "UPDATE", "Focal person's update"
    OUTGOING = "OUTGOING", "Outgoing communication"


class SupportingFile(models.Model):
    """
    A file uploaded in Incoming or Outgoing Monitoring, held with its document.

    The document's own file and its versions are the document itself. These
    are the papers that came with the work on it - a focal person's supporting
    attachment, the reply sent - captured here so that every file uploaded to
    the system is in the register. The row points at the file already stored
    by the module it came from rather than copying it, and is never edited:
    a replaced file is captured again as a new row.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="supporting_files"
    )
    source = models.CharField(max_length=10, choices=FileSource.choices)
    title = models.CharField(max_length=255)
    file = models.FileField(max_length=255, blank=True)
    incoming_update = models.ForeignKey(
        "incoming.IncomingUpdate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    outgoing = models.ForeignKey(
        "outgoing.OutgoingDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    uploaded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "supporting file"
        ordering = ("-uploaded_at", "-id")

    def __str__(self):
        return f"{self.document.reference_number} - {self.title}"

    @property
    def file_name(self):
        return os.path.basename(self.file.name) if self.file else ""

    @property
    def file_type(self):
        if not self.file:
            return ""
        return os.path.splitext(self.file.name)[1].lstrip(".").upper() or "FILE"

    @property
    def file_size(self):
        try:
            return self.file.size
        except (ValueError, OSError):
            return 0

    @property
    def uploader_label(self):
        return self.uploaded_by.get_display_name() if self.uploaded_by_id else "System"


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


class DocumentEvent(models.Model):
    """
    One entry in a document's own trail.

    The system-wide audit log in `audit` records that a row changed; this
    records what happened to the document in the office's own words -
    registered, viewed, assigned, revised, archived, disposed of - and is shown
    on the record itself, because accountability nobody can see is not
    accountability.

    The actor's name and role are copied in, as in `audit.AuditEvent`: a trail
    that reads "archived by NULL" because the account was later removed is not
    a trail.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="events"
    )
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    actor_label = models.CharField(max_length=150, blank=True)
    actor_role = models.CharField(max_length=40, blank=True)

    event_type = models.CharField(
        max_length=20, choices=EventType.choices, db_index=True
    )
    detail = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "document event"
        ordering = ("-occurred_at", "-id")
        indexes = [
            models.Index(fields=("document", "-occurred_at")),
            models.Index(fields=("event_type", "-occurred_at")),
        ]

    def __str__(self):
        return f"{self.document.reference_number} - {self.get_event_type_display()}"

    @property
    def icon(self):
        return {
            EventType.REGISTERED: "inbox",
            EventType.UPLOADED: "upload",
            EventType.VIEWED: "view",
            EventType.DOWNLOADED: "download",
            EventType.EDITED: "edit",
            EventType.ASSIGNED: "users",
            EventType.REASSIGNED: "users",
            EventType.STATUS_CHANGED: "monitoring",
            EventType.VERSION_UPLOADED: "file",
            EventType.APPROVED: "check-circle",
            EventType.CANCELLED: "close",
            EventType.RETENTION_SET: "clock",
            EventType.ARCHIVED: "lock",
            EventType.RESTORED: "upload",
            EventType.DISPOSED: "delete",
        }.get(self.event_type, "info")

    @property
    def status_tone(self):
        """Maps onto the shared status vocabulary in core/status.py."""
        return {
            EventType.REGISTERED: "new",
            EventType.UPLOADED: "in_progress",
            EventType.VIEWED: "information",
            EventType.DOWNLOADED: "information",
            EventType.EDITED: "in_progress",
            EventType.ASSIGNED: "assigned",
            EventType.REASSIGNED: "assigned",
            EventType.STATUS_CHANGED: "in_progress",
            EventType.VERSION_UPLOADED: "in_progress",
            EventType.APPROVED: "completed",
            EventType.CANCELLED: "cancelled",
            EventType.RETENTION_SET: "pending",
            EventType.ARCHIVED: "archived",
            EventType.RESTORED: "active",
            EventType.DISPOSED: "rejected",
        }.get(self.event_type, "information")
