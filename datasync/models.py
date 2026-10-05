"""
One uploaded workbook and what became of it.

A batch is created when a file is uploaded and previewed, and it stays: after
it is committed it is the record of which file was synced, by whom, into which
module, and exactly which rows were created, updated or skipped and why. The
workbook itself is kept in protected storage, because a register of incoming
correspondence is not something the web server should hand out by URL.
"""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from programs.storage import protected_storage

from . import profiles


def batch_path(instance, filename):
    return f"datasync/{timezone.localdate():%Y/%m}/{filename}"


class BatchStatus(models.TextChoices):
    PREVIEW = "PREVIEW", "Awaiting confirmation"
    COMMITTED = "COMMITTED", "Committed"
    DISCARDED = "DISCARDED", "Discarded"


class SyncBatch(models.Model):
    module = models.CharField(max_length=20, choices=profiles.choices())
    file = models.FileField(upload_to=batch_path, storage=protected_storage)
    original_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=10, choices=BatchStatus.choices, default=BatchStatus.PREVIEW,
        db_index=True,
    )
    # Sheet names chosen for the sync. Empty means every sheet.
    sheets = models.JSONField(default=list, blank=True)
    # Choices made on the preview that change how rows are judged, e.g.
    # {"strict_types": true}. See the profile's target.
    options = models.JSONField(default=dict, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="+",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    committed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    committed_at = models.DateTimeField(null=True, blank=True)

    # What the file would do (while previewing) or did (once committed). See
    # `engine.Plan.summary` for the shape.
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "spreadsheet sync"
        verbose_name_plural = "spreadsheet syncs"
        ordering = ("-uploaded_at", "-id")

    def __str__(self):
        return f"{self.get_module_display()} - {self.original_name}"

    def get_absolute_url(self):
        return reverse("datasync:batch", args=[self.pk])

    @property
    def profile(self):
        return profiles.get_profile(self.module)

    @property
    def is_preview(self):
        return self.status == BatchStatus.PREVIEW

    @property
    def counts(self):
        return self.summary.get("counts", {})

    def delete_file(self):
        """Drop the stored workbook. `original_name` still says what it was."""
        if self.file:
            self.file.delete(save=False)


class RowStatus(models.TextChoices):
    VALID = "VALID", "Valid"
    WARNING = "WARNING", "Valid, with a warning"
    IMPORTED = "IMPORTED", "Imported"
    DUPLICATE = "DUPLICATE", "Duplicate"
    ERROR = "ERROR", "Error"
    IGNORED = "IGNORED", "Not a record"


# Rows that did not (or will not) become records, for the error report.
NOT_IMPORTED = (RowStatus.DUPLICATE, RowStatus.ERROR, RowStatus.IGNORED)


class SyncRow(models.Model):
    """
    One row of a migrated workbook and what became of it.

    Written for profiles in "migrate" mode, so a register of thousands of rows
    can be paged through and filtered on the preview, and the rows left out
    can be downloaded with their reasons. Rewritten when the preview is redrawn
    and again when the batch is committed, so it always describes the last plan.
    """

    batch = models.ForeignKey(SyncBatch, on_delete=models.CASCADE, related_name="rows")
    sheet = models.CharField(max_length=100)
    row_number = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=RowStatus.choices)
    key = models.CharField(max_length=255, blank=True)
    # The row's cells as read, plus what the check worked out (the incoming
    # document matched, the type as written). Display only.
    values = models.JSONField(default=dict, blank=True)
    messages = models.JSONField(default=list, blank=True)
    # The record the row became, once committed.
    record_id = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
        indexes = [models.Index(fields=("batch", "status"))]

    def __str__(self):
        return f"{self.sheet} row {self.row_number}: {self.get_status_display()}"

    @property
    def tone(self):
        """The status badge's tone."""
        return {
            RowStatus.VALID: "success",
            RowStatus.IMPORTED: "success",
            RowStatus.WARNING: "warning",
            RowStatus.DUPLICATE: "info",
            RowStatus.ERROR: "danger",
        }.get(self.status, "neutral")
