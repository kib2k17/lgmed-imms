from django.contrib import admin

from .models import CalendarActivity


@admin.register(CalendarActivity)
class CalendarActivityAdmin(admin.ModelAdmin):
    list_display = (
        "title", "activity_type", "start_date", "owner", "assigned_to",
        "section", "priority", "status", "visibility", "is_published",
    )
    list_filter = (
        "activity_type", "status", "priority", "visibility", "section",
        "is_published",
    )
    list_select_related = ("owner", "assigned_to", "section")
    search_fields = (
        "title", "location", "participants", "remarks",
        "owner__first_name", "owner__last_name",
    )
    autocomplete_fields = ("owner", "assigned_to", "lgu")
    date_hierarchy = "start_date"
