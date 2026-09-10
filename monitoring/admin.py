from django.contrib import admin

from .models import MonitoringActivity, MonitoringAttachment


class AttachmentInline(admin.TabularInline):
    model = MonitoringAttachment
    extra = 0


@admin.register(MonitoringActivity)
class MonitoringActivityAdmin(admin.ModelAdmin):
    list_display = ("title", "lgu", "monitoring_date", "status")
    list_filter = ("status", "lgu__province", "lgu__lgu_type")
    search_fields = ("title", "reference_number", "lgu__name", "monitoring_team")
    date_hierarchy = "monitoring_date"
    inlines = [AttachmentInline]
