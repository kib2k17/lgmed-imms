from django.contrib import admin

from .models import LGU, Province


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    list_display = ("name", "capital", "lgu_count")
    search_fields = ("name",)


@admin.register(LGU)
class LGUAdmin(admin.ModelAdmin):
    list_display = ("name", "lgu_type", "province", "compliance_status", "is_active")
    list_filter = ("lgu_type", "province", "compliance_status", "is_active")
    search_fields = ("name", "contact_person", "address")
    autocomplete_fields = ("province",)
