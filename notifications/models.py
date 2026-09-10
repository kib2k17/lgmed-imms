from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Category(models.TextChoices):
    """What kind of work the notification is about."""

    REVIEW = "REVIEW", "Awaiting review"
    OVERDUE = "OVERDUE", "Overdue"
    PUBLICATION = "PUBLICATION", "Awaiting publication"
    ASSIGNMENT = "ASSIGNMENT", "Assigned to you"
    ACCOUNT = "ACCOUNT", "Account"
    SYSTEM = "SYSTEM", "System"


class Level(models.TextChoices):
    INFO = "INFO", "Information"
    ACTION = "ACTION", "Needs action"
    URGENT = "URGENT", "Urgent"


class NotificationQuerySet(models.QuerySet):
    def unread(self):
        return self.filter(read_at__isnull=True, dismissed_at__isnull=True)

    def visible(self):
        return self.filter(dismissed_at__isnull=True)

    def for_user(self, user):
        return self.filter(recipient=user)


class Notification(models.Model):
    """
    One item of work brought to a person's attention.

    Notifications are addressed to a named recipient rather than broadcast to a
    role, so "7 unread" means seven things *you* have not dealt with. The
    `dedupe_key` stops the same standing condition - a report that has been
    awaiting review for three weeks - from producing a new notification every
    time the digest runs.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.SYSTEM, db_index=True
    )
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)

    title = models.CharField(max_length=200)
    message = models.CharField(max_length=400, blank=True)
    url = models.CharField(
        max_length=255, blank=True, help_text="Where the recipient should go to act."
    )

    dedupe_key = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text=(
            "Identifies the underlying condition, so a standing issue is not "
            "re-notified on every run."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("recipient", "read_at", "-created_at")),
            models.Index(fields=("recipient", "dedupe_key")),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("notifications:open", args=[self.pk])

    # -- state ----------------------------------------------------------

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])

    def dismiss(self):
        now = timezone.now()
        self.dismissed_at = now
        if self.read_at is None:
            self.read_at = now
        self.save(update_fields=["dismissed_at", "read_at"])

    # -- presentation ----------------------------------------------------

    @property
    def icon(self):
        return {
            Category.REVIEW: "clock",
            Category.OVERDUE: "warning",
            Category.PUBLICATION: "documents",
            Category.ASSIGNMENT: "monitoring",
            Category.ACCOUNT: "user",
            Category.SYSTEM: "info",
        }.get(self.category, "info")

    @property
    def status_tone(self):
        """Maps onto the shared status vocabulary in core/status.py."""
        return {
            Level.URGENT: "critical",
            Level.ACTION: "pending",
            Level.INFO: "information",
        }.get(self.level, "information")
