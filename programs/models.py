from django.db import models
from django.urls import reverse

from core.models import TimeStampedModel


class ProgramCategory(models.Model):
    """Reference list of program categories, editable in System Settings."""

    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "program categories"
        ordering = ("name",)

    def __str__(self):
        return self.name


class ProgramStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    PENDING = "PENDING", "Pending"
    ARCHIVED = "ARCHIVED", "Archived"


class Program(TimeStampedModel):
    """A program or project administered by the Division."""

    title = models.CharField("program title", max_length=255)
    reference_number = models.CharField(
        max_length=60,
        blank=True,
        help_text="Issuance or reference number, if any.",
    )
    category = models.ForeignKey(
        ProgramCategory, on_delete=models.PROTECT, related_name="programs"
    )
    description = models.TextField(blank=True)
    objectives = models.TextField(
        blank=True, help_text="What the program is intended to achieve."
    )

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ProgramStatus.choices,
        default=ProgramStatus.PENDING,
        db_index=True,
    )

    lead_office = models.CharField(
        max_length=150,
        blank=True,
        default="Local Government Monitoring and Evaluation Division",
    )
    focal_person = models.CharField(max_length=150, blank=True)
    covered_lgus = models.ManyToManyField(
        "lgus.LGU",
        blank=True,
        related_name="programs",
        verbose_name="covered LGUs",
        help_text="Leave empty if the program covers the whole region.",
    )

    class Meta:
        ordering = ("-start_date", "title")
        indexes = [models.Index(fields=("status", "start_date"))]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("programs:detail", args=[self.pk])

    @property
    def year(self):
        return self.start_date.year if self.start_date else None

    @property
    def coverage_label(self):
        count = self.covered_lgus.count()
        if count == 0:
            return "Region-wide"
        return f"{count} LGU{'s' if count != 1 else ''}"
