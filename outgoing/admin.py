from django.contrib import admin

from .models import ControlCodeCounter, OutgoingDocument


@admin.register(ControlCodeCounter)
class ControlCodeCounterAdmin(admin.ModelAdmin):
    list_display = ("year", "last_number")


@admin.register(OutgoingDocument)
class OutgoingDocumentAdmin(admin.ModelAdmin):
    list_display = ("control_code", "date_sent", "communication_type", "sent_to")
    list_filter = ("communication_type", "sent_via")
    search_fields = ("control_code", "subject", "sent_to", "incoming_reference")
    date_hierarchy = "date_sent"
