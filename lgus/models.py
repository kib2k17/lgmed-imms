from django.db import models
from django.urls import reverse

from core.models import TimeStampedModel


class Province(models.Model):
    """A province of Region XIII (Caraga)."""

    name = models.CharField(max_length=120, unique=True)
    capital = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    @property
    def lgu_count(self):
        return self.lgus.count()


class LGUType(models.TextChoices):
    PROVINCE = "PROVINCE", "Province"
    CITY = "CITY", "City"
    MUNICIPALITY = "MUNICIPALITY", "Municipality"


class IncomeClass(models.TextChoices):
    FIRST = "1", "1st class"
    SECOND = "2", "2nd class"
    THIRD = "3", "3rd class"
    FOURTH = "4", "4th class"
    FIFTH = "5", "5th class"
    SIXTH = "6", "6th class"


class ComplianceStatus(models.TextChoices):
    COMPLIANT = "COMPLIANT", "Compliant"
    PARTIAL = "PARTIAL", "Partially compliant"
    NON_COMPLIANT = "NON_COMPLIANT", "Non-compliant"
    NOT_ASSESSED = "NOT_ASSESSED", "Not yet assessed"


class LGU(TimeStampedModel):
    """
    A local government unit under the Division's oversight.

    Highly urbanised and component cities are recorded with their province for
    geographic grouping even where they are administratively independent of
    it; `is_independent` records that distinction.
    """

    name = models.CharField("LGU name", max_length=150)
    lgu_type = models.CharField(
        "LGU type", max_length=20, choices=LGUType.choices, db_index=True
    )
    province = models.ForeignKey(
        Province, on_delete=models.PROTECT, related_name="lgus"
    )
    is_independent = models.BooleanField(
        "Independent of the province",
        default=False,
        help_text="Tick for highly urbanised or independent component cities.",
    )
    income_class = models.CharField(
        max_length=2, choices=IncomeClass.choices, blank=True
    )

    # Contact
    address = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(
        max_length=150,
        blank=True,
        help_text="Local Chief Executive or designated focal person.",
    )
    contact_position = models.CharField(max_length=120, blank=True)
    contact_number = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)

    # Oversight
    compliance_status = models.CharField(
        max_length=20,
        choices=ComplianceStatus.choices,
        default=ComplianceStatus.NOT_ASSESSED,
        db_index=True,
    )
    is_active = models.BooleanField("Active in the directory", default=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "LGU"
        verbose_name_plural = "LGUs"
        ordering = ("province__name", "lgu_type", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("name", "province"), name="unique_lgu_name_per_province"
            )
        ]
        indexes = [models.Index(fields=("lgu_type", "compliance_status"))]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("lgus:detail", args=[self.pk])

    # -- derived from the monitoring records ---------------------------

    @property
    def latest_monitoring(self):
        return self.monitoring_activities.order_by("-monitoring_date").first()

    @property
    def latest_monitoring_date(self):
        activity = self.latest_monitoring
        return activity.monitoring_date if activity else None

    @property
    def monitoring_count(self):
        return self.monitoring_activities.count()

    @property
    def compliance_tone(self):
        """Maps onto the shared status vocabulary in core/status.py."""
        return {
            ComplianceStatus.COMPLIANT: "compliant",
            ComplianceStatus.PARTIAL: "partial",
            ComplianceStatus.NON_COMPLIANT: "non_compliant",
            ComplianceStatus.NOT_ASSESSED: "not_started",
        }[self.compliance_status]
