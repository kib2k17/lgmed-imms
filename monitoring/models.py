import os

from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel


class MonitoringStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    FOR_REVIEW = "FOR_REVIEW", "For review"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class MonitoringActivity(TimeStampedModel):
    """
    A single monitoring or validation activity carried out on an LGU.

    This is the Division's core operational record: what was looked at, by
    whom, what was found, what was recommended, and what happens next.
    """

    title = models.CharField(
        "activity",
        max_length=255,
        help_text="For example: SGLG Assessment - Table Validation.",
    )
    reference_number = models.CharField(max_length=60, blank=True)
    lgu = models.ForeignKey(
        "lgus.LGU",
        on_delete=models.PROTECT,
        related_name="monitoring_activities",
        verbose_name="LGU",
    )
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monitoring_activities",
        help_text="The program this activity was conducted under, if any.",
    )

    monitoring_date = models.DateField(db_index=True)
    monitoring_team = models.CharField(
        max_length=255,
        help_text="Names of the personnel who conducted the activity.",
    )

    findings = models.TextField(
        blank=True, help_text="Observations made during the activity."
    )
    recommendations = models.TextField(blank=True)
    follow_up_action = models.TextField(blank=True)
    follow_up_date = models.DateField(
        null=True, blank=True, verbose_name="follow-up due date"
    )

    status = models.CharField(
        max_length=20,
        choices=MonitoringStatus.choices,
        default=MonitoringStatus.SCHEDULED,
        db_index=True,
    )

    class Meta:
        verbose_name_plural = "monitoring activities"
        ordering = ("-monitoring_date", "-id")
        indexes = [models.Index(fields=("status", "monitoring_date"))]

    def __str__(self):
        return f"{self.title} - {self.lgu}"

    def get_absolute_url(self):
        return reverse("monitoring:detail", args=[self.pk])

    @property
    def province(self):
        return self.lgu.province

    @property
    def is_overdue(self):
        """A follow-up whose due date has passed while work is outstanding."""
        return bool(
            self.follow_up_date
            and self.follow_up_date < timezone.localdate()
            and self.status
            not in (MonitoringStatus.COMPLETED, MonitoringStatus.CANCELLED)
        )

    @property
    def display_status(self):
        """Overdue outranks the stored status when the record is shown."""
        return "overdue" if self.is_overdue else self.status

    @property
    def timeline(self):
        """Ordered stages for the record's progress indicator."""
        order = [
            (MonitoringStatus.SCHEDULED, "Scheduled"),
            (MonitoringStatus.IN_PROGRESS, "Conducted"),
            (MonitoringStatus.FOR_REVIEW, "For review"),
            (MonitoringStatus.COMPLETED, "Completed"),
        ]
        if self.status == MonitoringStatus.CANCELLED:
            return [{"label": "Cancelled", "state": "cancelled"}]

        keys = [key for key, _ in order]
        current = keys.index(self.status) if self.status in keys else 0
        # "Completed" is the end of the road, not a stage still being worked
        # on, so it reads as done rather than as the current step - a finished
        # record should show four green ticks, not three and a numbered marker.
        finished = self.status == MonitoringStatus.COMPLETED
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


def attachment_path(instance, filename):
    return f"monitoring/{instance.activity_id}/{filename}"


class MonitoringAttachment(models.Model):
    """A supporting document filed against a monitoring activity."""

    activity = models.ForeignKey(
        MonitoringActivity, on_delete=models.CASCADE, related_name="attachments"
    )
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to=attachment_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ("-uploaded_at",)

    def __str__(self):
        return self.title

    @property
    def extension(self):
        return os.path.splitext(self.file.name)[1].lstrip(".").upper()

    @property
    def size(self):
        try:
            return self.file.size
        except (ValueError, OSError):
            return 0
