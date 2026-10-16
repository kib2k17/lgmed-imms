"""
Read-only views of the module's tables for the System Administrator.

Deadlines are set and files uploaded through the module, where the rules and
the trail are enforced; the Django admin is for looking, not for editing
around them.
"""

from django.contrib import admin

from .models import (
    MonthlyStaffSubmission,
    MonthlySubmissionAuditLog,
    MonthlySubmissionNotification,
    MonthlySubmissionSchedule,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MonthlySubmissionSchedule)
class ScheduleAdmin(ReadOnlyAdmin):
    list_display = ("__str__", "deadline", "created_by", "updated_at")
    list_filter = ("reporting_year",)


@admin.register(MonthlyStaffSubmission)
class SubmissionAdmin(ReadOnlyAdmin):
    list_display = ("staff", "schedule", "mmia_uploaded_at", "dtr_uploaded_at",
                    "completed_at")
    list_filter = ("schedule",)
    search_fields = ("staff__username", "staff__first_name", "staff__last_name")
    exclude = ("mmia_file", "dtr_file")


@admin.register(MonthlySubmissionNotification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ("notification_type", "recipient", "schedule", "email_status",
                    "attempts", "sent_at", "created_at")
    list_filter = ("notification_type", "email_status")
    search_fields = ("recipient__username", "email_address", "dedupe_key")


@admin.register(MonthlySubmissionAuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "action", "user_label", "staff", "schedule",
                    "document_kind")
    list_filter = ("action",)
    search_fields = ("user_label", "details")
