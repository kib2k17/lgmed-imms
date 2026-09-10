"""Shared model foundations."""

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """
    Records who created a record and who last changed it, and when.

    Government records need provenance: an auditor asking "who encoded this
    and when" must be able to see the answer on the record itself. The Phase 3
    audit log builds on these same fields.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="encoded by",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="last updated by",
    )

    class Meta:
        abstract = True
