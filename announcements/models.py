"""
News, advisories and commendations published to the public website.

The Division's public presence is, in practice, a news feed: what the office
did this week, which advisory LGUs must act on, which commendation the region
received. One record type carries all of it, distinguished by category, so a
communications officer encodes an item once and it appears wherever it belongs
- the homepage lead, the news page, the About page's commendations.
"""

from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator, slugify

from core.models import TimeStampedModel

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif")


class AnnouncementCategory(models.TextChoices):
    NEWS = "NEWS", "News"
    ADVISORY = "ADVISORY", "Advisory"
    ISSUANCE = "ISSUANCE", "Issuance"
    ACTIVITY = "ACTIVITY", "Activity"
    COMMENDATION = "COMMENDATION", "Commendation"


def announcement_image_path(instance, filename):
    return f"announcements/{instance.published_on:%Y/%m}/{filename}"


class AnnouncementQuerySet(models.QuerySet):
    def published(self):
        """Live items only: flagged for publication and not post-dated."""
        return self.filter(is_published=True, published_on__lte=timezone.localdate())

    def news(self):
        return self.exclude(category=AnnouncementCategory.COMMENDATION)

    def commendations(self):
        return self.filter(category=AnnouncementCategory.COMMENDATION)


class Announcement(TimeStampedModel):
    """A dated item on the public news feed."""

    title = models.CharField("headline", max_length=255)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        blank=True,
        help_text="Left blank, this is generated from the headline.",
    )
    category = models.CharField(
        max_length=20,
        choices=AnnouncementCategory.choices,
        default=AnnouncementCategory.NEWS,
        db_index=True,
    )
    published_on = models.DateField(
        "date published",
        default=timezone.localdate,
        db_index=True,
        help_text="The date shown on the item. A future date holds it back.",
    )
    summary = models.TextField(
        "lead paragraph",
        help_text="Two or three sentences. This is what appears in the news list.",
    )
    body = models.TextField(
        "full text",
        blank=True,
        help_text="Optional. One paragraph per line; shown on the item's own page.",
    )

    image = models.FileField(
        "photograph",
        upload_to=announcement_image_path,
        blank=True,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS)],
        help_text="JPG, PNG or WebP. Shown as the item's thumbnail.",
    )
    image_alt = models.CharField(
        "photograph description",
        max_length=255,
        blank=True,
        help_text="Describes the photograph for readers using a screen reader.",
    )

    location = models.CharField(
        max_length=150,
        blank=True,
        help_text="Where it happened, for example: Butuan City.",
    )
    source_url = models.URLField(
        "read more at",
        blank=True,
        help_text="Optional link to the full post or issuance elsewhere.",
    )

    is_published = models.BooleanField(
        "Published on the public website", default=False, db_index=True
    )
    is_featured = models.BooleanField(
        "Feature on the homepage",
        default=False,
        help_text="Featured items lead the homepage news section.",
    )

    objects = AnnouncementQuerySet.as_manager()

    class Meta:
        ordering = ("-published_on", "-created_at")
        indexes = [models.Index(fields=("is_published", "-published_on"))]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self):
        """
        A stable, readable public URL.

        Two activities in a week can legitimately carry the same headline, so a
        counter is appended rather than letting the save fail on the unique
        constraint - a communications officer should not have to invent a
        different title just to get a record saved.
        """
        base = slugify(self.title)[:240] or "announcement"
        candidate = base
        others = Announcement.objects.exclude(pk=self.pk)
        suffix = 2
        while others.filter(slug=candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def get_absolute_url(self):
        return reverse("announcements:detail", args=[self.pk])

    def get_public_url(self):
        return reverse("core:public_announcement", args=[self.slug])

    @property
    def status(self):
        return "published" if self.is_published else "draft"

    @property
    def is_live(self):
        return self.is_published and self.published_on <= timezone.localdate()

    @property
    def paragraphs(self):
        return [line.strip() for line in self.body.splitlines() if line.strip()]

    @property
    def excerpt(self):
        return Truncator(self.summary).chars(200)

    @property
    def alt_text(self):
        """Never an empty alt on a content image, and never a bare filename."""
        return self.image_alt or self.title
