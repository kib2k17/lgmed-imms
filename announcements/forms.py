from core.forms_base import GovModelForm

from .models import Announcement


class AnnouncementForm(GovModelForm):
    class Meta:
        model = Announcement
        fields = [
            "title", "category", "published_on", "location",
            "summary", "body",
            "image", "image_alt", "source_url",
            "is_published", "is_featured",
        ]

    fieldsets = [
        ("Item Details", ["title", "category", "published_on", "location"]),
        ("Text", ["summary", "body"]),
        ("Photograph and Source", ["image", "image_alt", "source_url"]),
        ("Publication", ["is_published", "is_featured"]),
    ]
    wide_fields = ("title", "summary", "body", "image_alt", "source_url")
