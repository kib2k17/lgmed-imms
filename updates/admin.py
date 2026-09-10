from django.contrib import admin

from .models import (
    DivisionUpdate,
    PopsPlanUpdate,
    ReportingPeriod,
    UpdateAttachment,
    WayForward,
)


class PopsPlanUpdateInline(admin.TabularInline):
    model = PopsPlanUpdate
    extra = 0


class WayForwardInline(admin.TabularInline):
    model = WayForward
    extra = 0


class AttachmentInline(admin.TabularInline):
    model = UpdateAttachment
    extra = 0


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ("label", "start_date", "end_date", "status", "is_public")
    list_filter = ("status", "is_public")
    search_fields = ("theme", "chief_remarks")
    date_hierarchy = "start_date"
    inlines = [PopsPlanUpdateInline, WayForwardInline]


@admin.register(DivisionUpdate)
class DivisionUpdateAdmin(admin.ModelAdmin):
    list_display = ("title", "period", "category", "status", "activity_date", "is_major")
    list_filter = ("category", "activity_type", "status", "is_major", "is_public")
    search_fields = ("title", "narrative", "remarks", "counterpart", "reference_number")
    date_hierarchy = "activity_date"
    inlines = [AttachmentInline]
