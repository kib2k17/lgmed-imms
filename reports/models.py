from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel


class ReportPeriod(models.TextChoices):
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    SEMESTRAL = "SEMESTRAL", "Semestral"
    ANNUAL = "ANNUAL", "Annual"
    SPECIAL = "SPECIAL", "Special report"


class ReportStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    FOR_REVIEW = "FOR_REVIEW", "For review"
    APPROVED = "APPROVED", "Approved"
    PUBLISHED = "PUBLISHED", "Published"
    RETURNED = "RETURNED", "Returned"


def report_path(instance, filename):
    return f"reports/{instance.year}/{filename}"


class Report(TimeStampedModel):
    """
    A monitoring or evaluation report moving from draft to publication.

    `submitted_on` and `published_on` are what the dashboard's monthly
    submission chart is built from, so they are set explicitly rather than
    inferred from the record's timestamps.
    """

    title = models.CharField("report title", max_length=255)
    reference_number = models.CharField(max_length=60, blank=True)
    period = models.CharField(
        "reporting period",
        max_length=20,
        choices=ReportPeriod.choices,
        default=ReportPeriod.QUARTERLY,
        db_index=True,
    )
    year = models.PositiveIntegerField(db_index=True)
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    summary = models.TextField(blank=True)

    prepared_by = models.CharField(max_length=150, blank=True)
    file = models.FileField(upload_to=report_path, blank=True)

    status = models.CharField(
        max_length=20,
        choices=ReportStatus.choices,
        default=ReportStatus.DRAFT,
        db_index=True,
    )
    submitted_on = models.DateField(null=True, blank=True)
    published_on = models.DateField(null=True, blank=True)
    review_remarks = models.TextField(
        blank=True, help_text="Notes from the reviewing officer."
    )

    class Meta:
        ordering = ("-year", "-submitted_on", "-created_at")
        indexes = [models.Index(fields=("status", "year"))]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("reports:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        """Keep the workflow dates consistent with the status."""
        today = timezone.localdate()
        if self.status != ReportStatus.DRAFT and not self.submitted_on:
            self.submitted_on = today
        if self.status == ReportStatus.PUBLISHED and not self.published_on:
            self.published_on = today
        if self.status != ReportStatus.PUBLISHED:
            self.published_on = None
        super().save(*args, **kwargs)

    @property
    def is_pending(self):
        return self.status in (
            ReportStatus.DRAFT,
            ReportStatus.SUBMITTED,
            ReportStatus.FOR_REVIEW,
            ReportStatus.RETURNED,
        )

    @property
    def workflow(self):
        order = [
            (ReportStatus.DRAFT, "Draft"),
            (ReportStatus.SUBMITTED, "Submitted"),
            (ReportStatus.FOR_REVIEW, "For review"),
            (ReportStatus.APPROVED, "Approved"),
            (ReportStatus.PUBLISHED, "Published"),
        ]
        if self.status == ReportStatus.RETURNED:
            return [{"label": "Returned for revision", "state": "cancelled"}]
        keys = [key for key, _ in order]
        current = keys.index(self.status) if self.status in keys else 0
        # "Published" is the end of the road, not a stage still being worked
        # on, so it reads as done rather than as the current step - a published
        # report should show five green ticks, not four and a numbered marker.
        finished = self.status == ReportStatus.PUBLISHED
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
