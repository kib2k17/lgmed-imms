from django.contrib import admin

from .models import (
    DisposalAuthority,
    Document,
    DocumentEvent,
    DocumentType,
    DocumentVersion,
)


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "retention_label", "is_active")
    list_filter = ("is_active", "retention_action")
    search_fields = ("name", "code")


@admin.register(DisposalAuthority)
class DisposalAuthorityAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "approved_on", "approved_by", "is_active")
    list_filter = ("is_active", "approved_on")
    search_fields = ("reference", "title", "approved_by")


class DocumentVersionInline(admin.TabularInline):
    """Read-only: a version history that can be edited is not a history."""

    model = DocumentVersion
    extra = 0
    can_delete = False
    readonly_fields = ("version_number", "file", "uploaded_at", "uploaded_by", "reason")

    def has_add_permission(self, request, obj=None):
        return False


class DocumentEventInline(admin.TabularInline):
    """The trail is append-only, here as everywhere else."""

    model = DocumentEvent
    extra = 0
    can_delete = False
    readonly_fields = (
        "occurred_at", "actor_label", "actor_role", "event_type", "detail",
        "from_status", "to_status", "ip_address",
    )
    fields = readonly_fields
    ordering = ("-occurred_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "reference_number", "title", "document_type", "status", "owner",
        "assigned_to", "retention_until", "retention_disposition",
    )
    list_filter = (
        "status", "retention_disposition", "document_type", "year", "is_public",
    )
    search_fields = ("reference_number", "title", "subject", "sender")
    date_hierarchy = "created_at"
    autocomplete_fields = ()
    readonly_fields = (
        "created_at", "updated_at", "reviewed_at", "approved_at", "completed_at",
        "archived_at", "disposed_at", "retention_reviewed_at",
    )
    inlines = [DocumentVersionInline, DocumentEventInline]


@admin.register(DocumentEvent)
class DocumentEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "document", "event_type", "actor_label", "detail")
    list_filter = ("event_type", "occurred_at")
    search_fields = ("document__reference_number", "actor_label", "detail")
    readonly_fields = [field.name for field in DocumentEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
