from django.contrib import admin

from .models import SyncBatch


@admin.register(SyncBatch)
class SyncBatchAdmin(admin.ModelAdmin):
    list_display = ("original_name", "module", "status", "uploaded_by", "uploaded_at",
                    "committed_at")
    list_filter = ("module", "status")
    search_fields = ("original_name",)
    readonly_fields = ("summary",)
