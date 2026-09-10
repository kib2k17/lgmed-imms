from django.contrib import admin

from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "period", "year", "status", "submitted_on", "published_on")
    list_filter = ("status", "period", "year")
    search_fields = ("title", "reference_number", "prepared_by")
