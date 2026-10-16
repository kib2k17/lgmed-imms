"""
Monthly Submissions: every staff member's MMIA and DTR, month by month.

Four tables, each answering one question:

  MonthlySubmissionSchedule      when is a reporting month's paperwork due?
                                 One row per month, set by the Division Chief.
  MonthlyStaffSubmission         what has one person handed in for that month?
                                 Exactly two slots - MMIA and DTR - and no more.
  MonthlySubmissionNotification  which email went to whom, and did it arrive?
                                 Its unique key is what stops a reminder going
                                 out twice when two scheduled runs overlap.
  MonthlySubmissionAuditLog      who did what - uploads, replacements,
                                 downloads, deadline changes, reminders.

A submission's status (not submitted / incomplete / completed / overdue) is
not stored. It depends on the clock as much as on the files, so it is worked
out when it is asked for - see `submissions.status`.
"""

import calendar
import os
import secrets
from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from programs.storage import protected_storage

# Every deadline is Philippine Standard Time, whatever the server's clock says.
MANILA = ZoneInfo("Asia/Manila")

MONTH_CHOICES = [(number, calendar.month_name[number]) for number in range(1, 13)]


class DocumentKind(models.TextChoices):
    """The two documents - the only two - a staff member submits each month."""

    MMIA = "mmia", "MMIA"
    DTR = "dtr", "DTR"


DOCUMENT_TITLES = {
    DocumentKind.MMIA: "Monthly Monitoring Individual Accomplishments",
    DocumentKind.DTR: "Daily Time Record",
}

DOCUMENT_DESCRIPTIONS = {
    DocumentKind.MMIA: "Upload your monthly individual accomplishments report.",
    DocumentKind.DTR: "Upload your Daily Time Record for the reporting month.",
}


def document_title(kind):
    return DOCUMENT_TITLES[DocumentKind(kind)]


# ---------------------------------------------------------------------------
# The schedule the Chief sets
# ---------------------------------------------------------------------------


class ScheduleQuerySet(models.QuerySet):
    def open(self, at=None):
        return self.filter(deadline__gt=at or timezone.now())

    def closed(self, at=None):
        return self.filter(deadline__lte=at or timezone.now())


class MonthlySubmissionSchedule(models.Model):
    """
    The deadline for one reporting month's MMIA and DTR.

    One row per month, enforced by the database. The Chief changes a deadline
    by editing this row - there is never a second schedule for the same month
    competing with the first. `deadline_set_at` records when the current
    deadline was decided, so reminders that would have fallen before that
    moment are not sent late on top of the announcement.
    """

    reporting_year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    reporting_month = models.PositiveSmallIntegerField(
        choices=MONTH_CHOICES,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    deadline = models.DateTimeField(
        help_text="Applies to both the MMIA and the DTR. Asia/Manila time.",
    )
    announcement = models.TextField(
        "announcement / instructions", blank=True, max_length=2000,
    )
    deadline_set_at = models.DateTimeField(default=timezone.now)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScheduleQuerySet.as_manager()

    class Meta:
        verbose_name = "monthly submission schedule"
        ordering = ("-reporting_year", "-reporting_month")
        constraints = [
            models.UniqueConstraint(
                fields=("reporting_year", "reporting_month"),
                name="monthly_submission_one_schedule_per_month",
            ),
        ]

    def __str__(self):
        return self.period_label

    def get_absolute_url(self):
        return f"{reverse('submissions:home')}?period={self.pk}"

    # -- presentation ---------------------------------------------------

    @property
    def period_label(self):
        return f"{calendar.month_name[self.reporting_month]} {self.reporting_year}"

    @property
    def period_start(self):
        return datetime(self.reporting_year, self.reporting_month, 1).date()

    @property
    def deadline_local(self):
        return self.deadline.astimezone(MANILA)

    @property
    def deadline_stamp(self):
        """Identifies this particular deadline, for notification keys."""
        return self.deadline_local.strftime("%Y%m%d%H%M")

    # -- state -----------------------------------------------------------

    def is_open(self, at=None):
        return (at or timezone.now()) < self.deadline

    def days_remaining(self, at=None):
        """Whole calendar days to the deadline date in Manila; 0 is today."""
        today = (at or timezone.now()).astimezone(MANILA).date()
        return (self.deadline_local.date() - today).days

    @staticmethod
    def combine(day, at_time):
        """A Manila date and time as an aware datetime."""
        return datetime.combine(day, at_time or time(17, 0), tzinfo=MANILA)


# ---------------------------------------------------------------------------
# What each staff member hands in
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = ("pdf", "doc", "docx", "xls", "xlsx")


def _stored_name(instance, filename, kind):
    """
    Where a submitted file is written, inside the protected root.

    The name the staff member's computer gave the file is never used on disk:
    it is kept in `*_original_name` for display and as the download name, and
    the stored name is built from the period, the account and a random token.
    That leaves nothing for a crafted filename to traverse or overwrite.
    """
    extension = os.path.splitext(filename)[1].lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        extension = "bin"
    schedule = instance.schedule
    return (
        f"monthly_submissions/{schedule.reporting_year}/"
        f"{schedule.reporting_month:02d}/{instance.staff_id}/"
        f"{kind}-{secrets.token_hex(8)}.{extension}"
    )


def mmia_upload_to(instance, filename):
    return _stored_name(instance, filename, DocumentKind.MMIA.value)


def dtr_upload_to(instance, filename):
    return _stored_name(instance, filename, DocumentKind.DTR.value)


class MonthlyStaffSubmission(models.Model):
    """
    One staff member's MMIA and DTR for one reporting month.

    Two fixed slots rather than a list of attachments, so the rule that a
    month asks for exactly these two documents is held by the table itself.
    One row per person per month; replacing a file before the deadline
    overwrites that slot. `completed_at` is set once, the first time both
    slots are filled, and is the "submitted on" date the Chief sees.
    """

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="monthly_submissions",
    )
    schedule = models.ForeignKey(
        MonthlySubmissionSchedule, on_delete=models.PROTECT,
        related_name="submissions",
    )

    mmia_file = models.FileField(
        "MMIA file", upload_to=mmia_upload_to, storage=protected_storage,
        max_length=255, blank=True,
    )
    mmia_original_name = models.CharField(max_length=255, blank=True)
    mmia_size = models.PositiveBigIntegerField(null=True, blank=True)
    mmia_uploaded_at = models.DateTimeField(null=True, blank=True)

    dtr_file = models.FileField(
        "DTR file", upload_to=dtr_upload_to, storage=protected_storage,
        max_length=255, blank=True,
    )
    dtr_original_name = models.CharField(max_length=255, blank=True)
    dtr_size = models.PositiveBigIntegerField(null=True, blank=True)
    dtr_uploaded_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "monthly staff submission"
        ordering = ("-schedule__reporting_year", "-schedule__reporting_month",
                    "staff__last_name", "staff__first_name")
        constraints = [
            models.UniqueConstraint(
                fields=("staff", "schedule"),
                name="monthly_submission_one_per_staff_per_month",
            ),
        ]

    def __str__(self):
        return f"{self.staff} - {self.schedule}"

    def get_absolute_url(self):
        return reverse(
            "submissions:review", args=[self.schedule_id, self.staff_id]
        )

    # -- the two slots, addressed by kind ---------------------------------

    def file_for(self, kind):
        return getattr(self, f"{DocumentKind(kind).value}_file")

    def has(self, kind):
        return bool(self.file_for(kind))

    def original_name(self, kind):
        return getattr(self, f"{DocumentKind(kind).value}_original_name")

    def size(self, kind):
        return getattr(self, f"{DocumentKind(kind).value}_size")

    def uploaded_at(self, kind):
        return getattr(self, f"{DocumentKind(kind).value}_uploaded_at")

    @property
    def uploaded_count(self):
        return sum(1 for kind in DocumentKind if self.has(kind))

    @property
    def is_complete(self):
        return self.uploaded_count == len(DocumentKind)

    @property
    def last_uploaded_at(self):
        stamps = [self.uploaded_at(kind) for kind in DocumentKind if self.has(kind)]
        return max(stamps) if stamps else None


# ---------------------------------------------------------------------------
# Emails sent, and the module's own trail
# ---------------------------------------------------------------------------


class NotificationType(models.TextChoices):
    ANNOUNCEMENT = "ANNOUNCEMENT", "Deadline announcement"
    DEADLINE_CHANGED = "DEADLINE_CHANGED", "Deadline changed"
    REMINDER = "REMINDER", "Upcoming deadline reminder"
    MANUAL_REMINDER = "MANUAL_REMINDER", "Reminder sent by the Chief"
    COMPLETED = "COMPLETED", "Submission completed"
    OVERDUE = "OVERDUE", "Overdue submission"


class EmailStatus(models.TextChoices):
    PENDING = "PENDING", "Waiting to be sent"
    SENDING = "SENDING", "Being sent"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed - will be retried"
    SKIPPED = "SKIPPED", "Not sent"


class MonthlySubmissionNotification(models.Model):
    """
    One email to one person about one schedule.

    Written *before* the email is sent, under a unique `dedupe_key`. Two
    reminder runs that overlap both try to write the same key; the database
    accepts one and the other skips, so nobody is emailed twice. A row is
    claimed for sending by a conditional update, which is atomic, and a
    failure leaves the row FAILED for the next run to retry.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="monthly_submission_notices",
    )
    schedule = models.ForeignKey(
        MonthlySubmissionSchedule, on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(
        max_length=20, choices=NotificationType.choices, db_index=True,
    )
    dedupe_key = models.CharField(max_length=191, unique=True)
    params = models.JSONField(default=dict, blank=True)

    email_status = models.CharField(
        max_length=10, choices=EmailStatus.choices, default=EmailStatus.PENDING,
        db_index=True,
    )
    email_address = models.CharField(max_length=254, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "monthly submission email"
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.get_notification_type_display()} to {self.recipient}"


class AuditAction(models.TextChoices):
    SCHEDULE_CREATED = "SCHEDULE_CREATED", "Deadline set"
    DEADLINE_EXTENDED = "DEADLINE_EXTENDED", "Deadline extended"
    DEADLINE_CHANGED = "DEADLINE_CHANGED", "Deadline changed"
    ANNOUNCEMENT_UPDATED = "ANNOUNCEMENT_UPDATED", "Announcement updated"
    UPLOADED = "UPLOADED", "Document uploaded"
    REPLACED = "REPLACED", "Document replaced"
    COMPLETED = "COMPLETED", "Submission completed"
    UPLOAD_REFUSED = "UPLOAD_REFUSED", "Upload refused"
    VIEWED = "VIEWED", "Document viewed"
    DOWNLOADED = "DOWNLOADED", "Document downloaded"
    REMINDER_SENT = "REMINDER_SENT", "Reminder sent"
    EXPORTED = "EXPORTED", "Compliance report exported"


class MonthlySubmissionAuditLog(models.Model):
    """
    The module's own trail. Append-only; nothing in the system edits a row.

    `staff` is whose submission the entry is about, which is not always the
    person who acted: a Chief downloading a DTR is `user` = the Chief,
    `staff` = the owner of the DTR.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )
    user_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=24, choices=AuditAction.choices, db_index=True)
    schedule = models.ForeignKey(
        MonthlySubmissionSchedule, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="audit_entries",
    )
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )
    document_kind = models.CharField(
        max_length=8, choices=DocumentKind.choices, blank=True,
    )
    details = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "monthly submission audit entry"
        verbose_name_plural = "monthly submission audit log"
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.get_action_display()} - {self.user_label or 'System'}"
