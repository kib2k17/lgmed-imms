from django.contrib import admin

from .models import PublicSiteContent, SystemSetting


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "public_site_enabled", "updated_at")


@admin.register(PublicSiteContent)
class PublicSiteContentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "telephone", "email", "updated_at")
