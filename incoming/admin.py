from django.contrib import admin

from .models import IncomingDocument, IncomingEvent, IncomingUpdate


class UpdateInline(admin.TabularInline):
    model = IncomingUpdate
    extra = 0
    fields = ("created_at", "created_by", "status", "action_taken", "remarks")
    readonly_fields = ("created_at",)


class EventInline(admin.TabularInline):
    """The trail is written by the workflow, never by hand."""

    model = IncomingEvent
    extra = 0
    can_delete = False
    fields = ("occurred_at", "actor_label", "event_type", "detail")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(IncomingDocument)
class IncomingDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "docket_number", "subject", "document_type", "date_received", "status",
        "assigned_to", "due_date",
    )
    list_filter = ("status", "priority", "document_type", "assigned_to")
    search_fields = ("docket_number", "subject", "source_office")
    date_hierarchy = "date_received"
    inlines = [UpdateInline, EventInline]


@admin.register(IncomingUpdate)
class IncomingUpdateAdmin(admin.ModelAdmin):
    list_display = ("document", "created_at", "created_by", "status")
    list_filter = ("status",)
    search_fields = ("document__docket_number", "action_taken")


@admin.register(IncomingEvent)
class IncomingEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "document", "event_type", "actor_label")
    list_filter = ("event_type",)
    search_fields = ("document__docket_number", "actor_label", "detail")
