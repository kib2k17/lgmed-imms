from django.contrib import admin

from .models import FrontlineService


@admin.register(FrontlineService)
class FrontlineServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "service_type", "processing_time", "is_published")
    list_filter = ("service_type", "is_published")
    search_fields = ("name", "description", "clients")
