"""
Incoming documents, from the moment they arrive at the counter until they are
closed.

This module replaces the spreadsheet the Division kept for incoming
correspondence. The rule the spreadsheet could not enforce, and which this
model exists to enforce, is that an encoder records what arrived but does not
decide who handles it: a document sits at "For Division Chief review" until the
Chief has read it, noted what is required, and named a focal person.

Three tables, because three different things are being remembered:

  IncomingDocument  the document and where it currently stands
  IncomingUpdate    what the focal person has actually done about it
  IncomingEvent     the trail - who did what to it, and when
"""

import os
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Max, Q
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel

# How long an assigned document may go without an update from its focal person
# before the Chief's dashboard counts it as awaiting one.
UPDATE_REMINDER_DAYS = 7


class IncomingStatus(models.TextChoices):
    FOR_REVIEW = "FOR_REVIEW", "For Division Chief review"
    ASSIGNED = "ASSIGNED", "Assigned"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    FOR_ACTION = "FOR_ACTION", "For action"
    PENDING = "PENDING", "Pending"
    RETURNED = "RETURNED", "Returned / for revision"
    COMPLETED = "COMPLETED", "Completed"
    # Brought in from the office's spreadsheet register by `datasync`. The
    # register records what arrived and the Chief's routing note, but not who
    # in the system handles it, so an imported row stands outside the workflow
    # until the Chief assigns it - and is kept out of the review queue, the
    # overdue counts and the standing notices, which would otherwise raise a
    # notice for every historical row.
    IMPORTED = "IMPORTED", "Imported from spreadsheet"


# Everything that is not finished and is in the workflow. Used for "open",
# "overdue" and the counts on the Chief's dashboard, so the definition lives in
# exactly one place.
OPEN_STATUSES = tuple(
    value
    for value in IncomingStatus.values
    if value not in (IncomingStatus.COMPLETED, IncomingStatus.IMPORTED)
)

# The statuses a focal person may report on an update. Assignment,
# acknowledgement and return are recorded by the workflow itself rather than
# chosen from a menu.
FOCAL_STATUSES = (
    IncomingStatus.IN_PROGRESS,
    IncomingStatus.FOR_ACTION,
    IncomingStatus.PENDING,
    IncomingStatus.COMPLETED,
)


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class EventType(models.TextChoices):
    RECORDED = "RECORDED", "Received and recorded"
    EDITED = "EDITED", "Record amended"
    REVIEWED = "REVIEWED", "Reviewed by the Division Chief"
    ASSIGNED = "ASSIGNED", "Assigned to a focal person"
    REASSIGNED = "REASSIGNED", "Reassigned"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged by the focal person"
    UPDATED = "UPDATED", "Update provided"
    RETURNED = "RETURNED", "Returned for revision"
    COMPLETED = "COMPLETED", "Completed"
    OUTGOING = "OUTGOING", "Outgoing communication recorded"


def incoming_path(instance, filename):
    received = instance.date_received or timezone.localdate()
    return f"incoming/{received:%Y/%m}/{filename}"


def update_path(instance, filename):
    return f"incoming/updates/{instance.document_id}/{filename}"


class IncomingDocumentQuerySet(models.QuerySet):
    """The questions the Chief's dashboard and the filters actually ask."""

    def open(self):
        return self.filter(status__in=OPEN_STATUSES)

    def for_review(self):
        return self.filter(status=IncomingStatus.FOR_REVIEW)

    def completed(self):
        return self.filter(status=IncomingStatus.COMPLETED)

    def assigned_to(self, user):
        return self.filter(assigned_to=user)

    def overdue(self, today=None):
        """Past its action due date while the work is still outstanding."""
        return self.open().filter(
            due_date__isnull=False, due_date__lt=today or timezone.localdate()
        )

    def awaiting_acknowledgement(self):
        return self.filter(status=IncomingStatus.ASSIGNED, acknowledged_at__isnull=True)

    def with_latest_update(self):
        return self.annotate(latest_update_at=Max("updates__created_at"))

    def awaiting_update(self, days=UPDATE_REMINDER_DAYS, now=None):
        """
        Assigned, unfinished, and nothing heard for `days`.

        Measured from the last update where there is one and from the
        assignment where there is not, so a document assigned this morning is
        not already counted as silent.
        """
        cutoff = (now or timezone.now()) - timedelta(days=days)
        return (
            self.open()
            .filter(assigned_to__isnull=False)
            .with_latest_update()
            .filter(
                Q(latest_update_at__lt=cutoff)
                | Q(latest_update_at__isnull=True, assigned_at__lt=cutoff)
            )
        )


class IncomingDocument(TimeStampedModel):
    """One document received by the Division, and its progress through the office."""

    docket_number = models.CharField(
        "DNS number",
        max_length=60,
        unique=True,
        db_index=True,
        help_text="The office's own reference for this document, e.g. 2026-0417.",
    )
    # Empty until the Division Chief assigns a focal person; issued once, then
    # the document's primary tracking number. See outgoing/codes.py. Not
    # editable: no form may carry it, so it cannot be typed in or changed.
    lgmed_code = models.CharField(
        "LGMED code",
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    # 500 rather than 255: the register's subjects run to well over 300
    # characters, and a subject cut short is a different subject.
    subject = models.CharField(max_length=500)
    document_type = models.ForeignKey(
        "documents.DocumentType",
        on_delete=models.PROTECT,
        related_name="incoming_documents",
    )
    date_received = models.DateField(db_index=True, default=timezone.localdate)
    source_office = models.CharField(
        "source / office",
        max_length=200,
        help_text="The office, agency or LGU the document came from.",
    )
    attachment = models.FileField(
        "document / file attachment", upload_to=incoming_path, blank=True
    )
    initial_remarks = models.TextField(
        blank=True, help_text="What the receiving officer noted on arrival."
    )

    status = models.CharField(
        max_length=20,
        choices=IncomingStatus.choices,
        default=IncomingStatus.FOR_REVIEW,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.NORMAL
    )
    due_date = models.DateField(
        "action due date",
        null=True,
        blank=True,
        help_text="The date by which the action should be completed.",
    )

    # -- the Division Chief's review --------------------------------------
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField("Division Chief's notes / instructions", blank=True)

    # -- assignment --------------------------------------------------------
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_assigned",
        verbose_name="focal person",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_assignments_made",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    assignment_remarks = models.TextField(
        "assignment remarks / instructions", blank=True
    )

    # -- the focal person's side -------------------------------------------
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = IncomingDocumentQuerySet.as_manager()

    class Meta:
        verbose_name = "incoming document"
        ordering = ("-date_received", "-id")
        indexes = [
            models.Index(fields=("status", "-date_received")),
            models.Index(fields=("assigned_to", "status")),
        ]

    def __str__(self):
        return f"{self.tracking_number} - {self.subject}"

    def get_absolute_url(self):
        return reverse("incoming:detail", args=[self.pk])

    # -- tracking -------------------------------------------------------------

    @property
    def tracking_number(self):
        """The LGMED code once one is issued; the DMS number until then."""
        return self.lgmed_code or self.docket_number

    @property
    def outgoing_document(self):
        """
        The Outgoing Monitoring record the action continues in.

        Opened when the focal person acknowledges the assignment; None before.
        """
        try:
            return self.outgoing_record
        except ObjectDoesNotExist:
            return None

    @property
    def action_url(self):
        """Where the work on this document is done: Outgoing, once it is there."""
        outgoing = self.outgoing_document
        return outgoing.get_absolute_url() if outgoing else self.get_absolute_url()

    def may_record_transmittal(self, user):
        """The focal person, or the Chief, records the communication sent."""
        if self.outgoing_document is None:
            return False
        return self.assigned_to_id == getattr(user, "pk", None) or bool(
            getattr(user, "can_review_incoming", False)
        )

    # -- state --------------------------------------------------------------

    @property
    def is_reviewed(self):
        return self.reviewed_at is not None

    @property
    def is_assigned(self):
        return self.assigned_to_id is not None

    @property
    def is_acknowledged(self):
        return self.acknowledged_at is not None

    @property
    def is_completed(self):
        return self.status == IncomingStatus.COMPLETED

    @property
    def is_overdue(self):
        return bool(
            self.due_date
            and not self.is_completed
            and self.due_date < timezone.localdate()
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
    def awaits_acknowledgement(self):
        return self.status == IncomingStatus.ASSIGNED and not self.is_acknowledged

    def may_be_acknowledged_by(self, user):
        return (
            self.is_assigned
            and self.assigned_to_id == getattr(user, "pk", None)
            and not self.is_acknowledged
        )

    def may_be_updated_by(self, user):
        """
        The focal person reports progress; the Chief may also close a record.

        Only once the assignment is acknowledged: that is when the document
        moves to Outgoing Monitoring, where all action on it is taken.
        """
        if self.is_completed or not self.is_assigned or not self.is_acknowledged:
            return False
        return self.assigned_to_id == getattr(user, "pk", None) or bool(
            getattr(user, "can_review_incoming", False)
        )

    # -- history -------------------------------------------------------------

    @property
    def latest_update(self):
        return self.updates.first()

    @property
    def update_count(self):
        return self.updates.count()

    @property
    def days_since_last_update(self):
        """Days since the last word from the focal person, or since assignment."""
        latest = self.latest_update
        reference = latest.created_at if latest else self.assigned_at
        if reference is None:
            return None
        return (timezone.now() - reference).days

    # -- turnaround, for the processing-time report ---------------------------

    @staticmethod
    def _days_between(start, end):
        """Whole days between two points, either of which may be absent."""
        if start is None or end is None:
            return None
        start_date = timezone.localtime(start).date() if hasattr(start, "hour") else start
        end_date = timezone.localtime(end).date() if hasattr(end, "hour") else end
        return (end_date - start_date).days

    @property
    def days_to_assign(self):
        return self._days_between(self.date_received, self.assigned_at)

    @property
    def days_to_acknowledge(self):
        return self._days_between(self.assigned_at, self.acknowledged_at)

    @property
    def days_to_complete(self):
        return self._days_between(self.date_received, self.completed_at)

    @property
    def days_open(self):
        return self._days_between(self.date_received, self.completed_at or timezone.now())

    # -- presentation ---------------------------------------------------------

    @property
    def file_type(self):
        if not self.attachment:
            return ""
        return os.path.splitext(self.attachment.name)[1].lstrip(".").upper() or "FILE"

    @property
    def file_size(self):
        try:
            return self.attachment.size
        except (ValueError, OSError):
            return 0

    @property
    def workflow(self):
        """Ordered stages for the record's progress indicator."""
        order = [
            (IncomingStatus.FOR_REVIEW, "Recorded"),
            (IncomingStatus.ASSIGNED, "Reviewed and assigned"),
            (IncomingStatus.ACKNOWLEDGED, "Acknowledged"),
            (IncomingStatus.IN_PROGRESS, "Action in progress"),
            (IncomingStatus.COMPLETED, "Completed"),
        ]
        if self.status == IncomingStatus.RETURNED:
            return [{"label": "Returned for revision", "state": "cancelled"}]

        # The statuses a focal person reports mid-flight all sit at the same
        # point of the journey: work is under way but is not finished.
        reached = {
            IncomingStatus.FOR_REVIEW: 0,
            IncomingStatus.ASSIGNED: 1,
            IncomingStatus.ACKNOWLEDGED: 2,
            IncomingStatus.IN_PROGRESS: 3,
            IncomingStatus.FOR_ACTION: 3,
            IncomingStatus.PENDING: 3,
            IncomingStatus.COMPLETED: 4,
            IncomingStatus.IMPORTED: 0,
        }
        current = reached.get(self.status, 0)
        # "Completed" is the end of the road, not a stage still being worked
        # on, so it reads as done rather than as the current step - a finished
        # document should show five green ticks, not four and a numbered marker.
        finished = self.status == IncomingStatus.COMPLETED
        return [
            {
                "label": label,
                "state": (
                    "done" if index < current or (finished and index == current)
                    else "current" if index == current
                    else "upcoming"
                ),
            }
            for index, (_key, label) in enumerate(order)
        ]


class IncomingUpdate(models.Model):
    """One report of progress from the focal person handling the document."""

    document = models.ForeignKey(
        IncomingDocument, on_delete=models.CASCADE, related_name="updates"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    action_taken = models.TextField("action taken")
    remarks = models.TextField(blank=True)
    status = models.CharField(
        "status after this action",
        max_length=20,
        choices=IncomingStatus.choices,
        default=IncomingStatus.IN_PROGRESS,
    )
    attachment = models.FileField(
        "supporting attachment", upload_to=update_path, blank=True
    )

    class Meta:
        verbose_name = "incoming document update"
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.document.docket_number} - {self.get_status_display()}"

    def get_absolute_url(self):
        return self.document.get_absolute_url()

    @property
    def extension(self):
        return os.path.splitext(self.attachment.name)[1].lstrip(".").upper()

    @property
    def size(self):
        try:
            return self.attachment.size
        except (ValueError, OSError):
            return 0


class IncomingEvent(models.Model):
    """
    One entry in a document's own trail.

    The system-wide audit log records that a row changed; this records what
    happened to the document in the office's own words - received, reviewed,
    assigned, acknowledged, acted on, completed - and is shown on the record
    itself, because accountability nobody can see is not accountability.

    The actor's name and role are copied in, as in `audit.AuditEvent`: a trail
    that reads "assigned by NULL" because the account was later removed is not
    a trail.
    """

    document = models.ForeignKey(
        IncomingDocument, on_delete=models.CASCADE, related_name="events"
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

    event_type = models.CharField(max_length=20, choices=EventType.choices)
    detail = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "incoming document event"
        ordering = ("occurred_at", "id")

    def __str__(self):
        return f"{self.document.docket_number} - {self.get_event_type_display()}"

    @property
    def icon(self):
        return {
            EventType.RECORDED: "inbox",
            EventType.EDITED: "edit",
            EventType.REVIEWED: "view",
            EventType.ASSIGNED: "users",
            EventType.REASSIGNED: "users",
            EventType.ACKNOWLEDGED: "check",
            EventType.UPDATED: "monitoring",
            EventType.RETURNED: "warning",
            EventType.COMPLETED: "check-circle",
            EventType.OUTGOING: "mail",
        }.get(self.event_type, "info")

    @property
    def status_tone(self):
        """Maps onto the shared status vocabulary in core/status.py."""
        return {
            EventType.RECORDED: "new",
            EventType.EDITED: "in_progress",
            EventType.REVIEWED: "in_progress",
            EventType.ASSIGNED: "assigned",
            EventType.REASSIGNED: "assigned",
            EventType.ACKNOWLEDGED: "acknowledged",
            EventType.UPDATED: "in_progress",
            EventType.RETURNED: "returned",
            EventType.COMPLETED: "completed",
            EventType.OUTGOING: "in_progress",
        }.get(self.event_type, "information")
