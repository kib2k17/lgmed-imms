from django.db import models
from django.urls import reverse

from core.models import TimeStampedModel


class ServiceType(models.TextChoices):
    SIMPLE = "SIMPLE", "Simple transaction"
    COMPLEX = "COMPLEX", "Complex transaction"
    TECHNICAL = "TECHNICAL", "Highly technical"


class FrontlineService(TimeStampedModel):
    """
    A frontline service of the Division, described the way a citizen's charter
    describes it: who it is for, what to bring, how long it takes, what it costs.
    """

    name = models.CharField("service name", max_length=200)
    service_type = models.CharField(
        max_length=20, choices=ServiceType.choices,
        default=ServiceType.SIMPLE, db_index=True,
    )
    description = models.TextField(blank=True)
    clients = models.CharField(
        max_length=255, blank=True,
        help_text="Who may avail of this service, e.g. LGUs, national agencies, public.",
    )
    requirements = models.TextField(
        blank=True, help_text="One requirement per line.",
    )
    processing_time = models.CharField(
        max_length=120, blank=True,
        help_text="For example: 3 working days.",
    )
    fees = models.CharField(
        max_length=120, blank=True, default="None",
        help_text="State 'None' where no fee is charged.",
    )
    responsible_office = models.CharField(
        max_length=150, blank=True,
        default="Local Government Monitoring and Evaluation Division",
    )
    responsible_person = models.CharField(max_length=150, blank=True)
    is_published = models.BooleanField(
        "Published on the public website", default=False,
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("services:detail", args=[self.pk])

    @property
    def requirement_list(self):
        return [line.strip() for line in self.requirements.splitlines() if line.strip()]

    @property
    def status(self):
        return "published" if self.is_published else "draft"
