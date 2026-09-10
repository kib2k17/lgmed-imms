from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "category", "level", "created_at", "read_at")
    list_filter = ("category", "level")
    search_fields = ("title", "message", "recipient__username", "dedupe_key")
    date_hierarchy = "created_at"
