from django.contrib import admin

from .models import Program, ProgramCategory


@admin.register(ProgramCategory)
class ProgramCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "is_active")
    search_fields = ("name",)


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "status", "start_date", "end_date")
    list_filter = ("status", "category")
    search_fields = ("title", "reference_number", "focal_person")
    filter_horizontal = ("covered_lgus",)
    date_hierarchy = "start_date"
