from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Section, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username", "get_display_name", "role", "section", "position", "is_active"
    )
    list_filter = ("role", "section", "is_active", "is_staff")
    list_select_related = ("section",)
    search_fields = ("username", "first_name", "last_name", "email", "position")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "LGMED-IMMS profile",
            {"fields": ("role", "section", "position", "office", "contact_number")},
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "LGMED-IMMS profile",
            {"fields": ("first_name", "last_name", "email", "role", "section", "position")},
        ),
    )


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "short_name")
