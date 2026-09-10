from django.contrib import admin

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "published_on", "is_published", "is_featured")
    list_filter = ("category", "is_published", "is_featured", "published_on")
    search_fields = ("title", "summary", "body")
    prepopulated_fields = {"slug": ("title",)}
