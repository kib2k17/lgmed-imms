from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only: the trail is append-only, in the admin as well."""

    list_display = ("timestamp", "actor_label", "action", "target_model", "target_label")
    list_filter = ("action", "target_model")
    search_fields = ("actor_label", "target_label", "detail", "ip_address")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
