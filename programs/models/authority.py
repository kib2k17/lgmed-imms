"""
The written authority - a memorandum - under which documents may be released
to the public website.

Part of programs.models - see its package docstring.
"""

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.models import TimeStampedModel

from ..storage import protected_storage
from .vocabulary import ALLOWED_EXTENSIONS, DocumentStatus


# ---------------------------------------------------------------------------
# The authority to publish
# ---------------------------------------------------------------------------


def authority_path(instance, filename):
    return f"ppa/authorities/{instance.reference_slug}/{filename}"


class PublicationAuthority(TimeStampedModel):
    """
    The written authority under which a file may be released to the public -
    normally a memorandum from the Regional Director or the Division Chief.

    Publication is the irreversible act in this module. A document that has
    been on the public website has been seen, and taking it down afterwards
    does not unsee it. So releasing one may not rest on a reviewer's opinion
    recorded as a tick: the office's authority to publish is written down
    first, and every file released is cited against it.

    This mirrors `documents.DisposalAuthority`, which guards the equivalent
    irreversible act in the document register, and for the same reason - it is
    what an auditor asks to see. "Who approved this?" is answered by the
    review trail; "under what authority was it released?" is answered here.

    One memorandum normally covers many files: a memorandum authorising the
    publication of the 2026 SGLG results authorises the whole set, and making
    the office record a separate authority per file would turn a real control
    into a formality people route around.
    """

    reference = models.CharField(
        max_length=120,
        unique=True,
        help_text="e.g. LGMED Memorandum No. 2026-014, or the issuance number.",
    )
    title = models.CharField(
        "subject",
        max_length=255,
        help_text="What the memorandum authorises, in its own words.",
    )
    approved_on = models.DateField("date issued")
    approved_by = models.CharField(
        max_length=200,
        help_text="The officer or body that issued it, e.g. the Regional Director.",
    )
    scope = models.TextField(
        blank=True,
        help_text="What this authority covers, and anything it excludes.",
    )

    # The memorandum itself, kept internally: it is the evidence behind the
    # release, not a thing being released. It is never copied to the public
    # side, and nothing here publishes it.
    memorandum = models.FileField(
        "scanned memorandum",
        upload_to=authority_path,
        storage=protected_storage,
        blank=True,
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
        help_text="The signed issuance. Stored internally; never published.",
    )

    effective_from = models.DateField(
        null=True, blank=True,
        help_text="Leave empty if it takes effect on the date it was issued.",
    )
    effective_until = models.DateField(
        null=True, blank=True,
        help_text="Leave empty if it does not expire.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Clear this to withdraw the authority. Files already "
                  "published under it stay published.",
    )

    class Meta:
        verbose_name = "publication authority"
        verbose_name_plural = "publication authorities"
        ordering = ("-approved_on", "reference")
        indexes = [models.Index(fields=("is_active", "-approved_on"))]

    def __str__(self):
        return f"{self.reference} - {self.title}"

    def get_absolute_url(self):
        return reverse("programs:authority_detail", args=[self.pk])

    def clean(self):
        super().clean()
        if (
            self.effective_from
            and self.effective_until
            and self.effective_until < self.effective_from
        ):
            raise ValidationError({
                "effective_until": "The end date must not be earlier than the start."
            })

    @property
    def reference_slug(self):
        return slugify(self.reference) or "authority"

    @property
    def start_date(self):
        return self.effective_from or self.approved_on

    def is_in_force(self, on=None):
        """
        Whether this authority permits a release today.

        Checked at the moment of publication rather than only at approval: a
        memorandum that has since been withdrawn or has run out must not still
        be letting files onto the public website.
        """
        if not self.is_active:
            return False
        on = on or timezone.localdate()
        if self.start_date and on < self.start_date:
            return False
        if self.effective_until and on > self.effective_until:
            return False
        return True

    @property
    def in_force(self):
        return self.is_in_force()

    @property
    def status_label(self):
        if not self.is_active:
            return "Withdrawn"
        today = timezone.localdate()
        if self.start_date and today < self.start_date:
            return "Not yet in effect"
        if self.effective_until and today > self.effective_until:
            return "Expired"
        return "In force"

    @property
    def status_tone(self):
        return "active" if self.in_force else "inactive"

    @property
    def released_count(self):
        return self.documents.filter(status=DocumentStatus.PUBLISHED).count()
