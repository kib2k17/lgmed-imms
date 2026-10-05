"""
Outgoing communications - what the Division sent, to whom, and how.

The register is kept as a spreadsheet and brought in by `datasync`; this model
holds it so it can be searched alongside everything else. Each row is keyed by
the office's LGMED code ("LGMED-13 - DBA - 2026-01-05-0001"), which carries
the date it was issued.
"""

import os

from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel


def outgoing_path(instance, filename):
    sent = instance.date_sent or timezone.localdate()
    return f"outgoing/{sent:%Y/%m}/{filename}"


class OutgoingDocument(TimeStampedModel):
    """
    One communication in Outgoing Monitoring.

    Two kinds of row live here. Rows from the spreadsheet register record what
    was sent before the system existed. Rows linked to an incoming document are
    opened when its focal person acknowledges the assignment: from then on the
    action - updates, return for revision, completion, and the communication
    finally sent - is carried out here, under the document's LGMED code.
    """

    control_code = models.CharField(
        max_length=255,
        unique=True,
        help_text="The LGMED code, e.g. LGMED-13 - DBA - 2026-01-05-0001.",
    )
    date_sent = models.DateField(
        null=True, blank=True, db_index=True,
        help_text="Read from the control code.",
    )
    communication_type = models.CharField(
        "type of communication", max_length=120, blank=True
    )
    # Text rather than a bounded string: the register's subjects run to 900
    # characters and its "sent to" lists to 400.
    subject = models.TextField("subject / title", blank=True)
    sent_to = models.TextField(blank=True)
    sent_via = models.CharField(max_length=150, blank=True)
    remarks = models.TextField(blank=True)
    incoming_reference = models.CharField(
        "DMS number (incoming)", max_length=120, blank=True,
        help_text="The incoming document this replies to, where there is one.",
    )
    dms_number = models.CharField("DMS number (outgoing)", max_length=120, blank=True)
    file = models.FileField(
        "file of the communication",
        upload_to=outgoing_path,
        blank=True,
        help_text="The communication as sent, e.g. the signed and scanned reply.",
    )
    incoming = models.OneToOneField(
        "incoming.IncomingDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outgoing_record",
        verbose_name="incoming document",
        help_text="The incoming document this action answers, where there is one.",
    )

    class Meta:
        verbose_name = "outgoing document"
        ordering = ("-date_sent", "-id")

    def __str__(self):
        return self.control_code

    def get_absolute_url(self):
        return reverse("outgoing:detail", args=[self.pk])

    @property
    def incoming_document(self):
        """The incoming document this communication answers, where there is one."""
        return self.incoming

    @property
    def file_name(self):
        return os.path.basename(self.file.name) if self.file else ""

    @property
    def file_type(self):
        if not self.file:
            return ""
        return os.path.splitext(self.file.name)[1].lstrip(".").upper() or "FILE"

    @property
    def is_sent(self):
        return self.date_sent is not None

    @property
    def display_status(self):
        """The action's status where it has one; otherwise sent or not."""
        if self.incoming_id:
            return self.incoming.display_status
        return "completed" if self.is_sent else "pending"

    @property
    def display_status_label(self):
        if self.incoming_id:
            return self.incoming.display_status_label
        return "Sent" if self.is_sent else "Not yet sent"


class ControlCodeCounter(models.Model):
    """
    The last LGMED code number issued in a year.

    Kept rather than recounted, so a number is never issued twice - not even
    after the document that carried it is deleted.
    """

    year = models.PositiveIntegerField(primary_key=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "LGMED code counter"

    def __str__(self):
        return f"{self.year}: {self.last_number:04d}"
