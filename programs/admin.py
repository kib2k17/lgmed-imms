from django.contrib import admin

from .models import (
    Activity,
    Program,
    ProgramCategory,
    Project,
    SubProject,
    SupportingDocument,
)


@admin.register(ProgramCategory)
class ProgramCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


class PPAAdmin(admin.ModelAdmin):
    """
    Read-mostly. The publication fields are not editable here on purpose:
    approving or publishing through the Django admin would bypass the review
    screen, the screening and the checks that go with them.
    """

    list_display = ("title", "status", "publication_status", "updated_at")
    list_filter = ("publication_status", "status")
    search_fields = ("title", "description")
    readonly_fields = (
        "slug", "public_token", "publication_status",
        "submitted_at", "submitted_by", "reviewed_at", "reviewed_by",
        "approved_at", "approved_by", "published_at", "published_by",
        "unpublished_at", "unpublished_by", "archived_at", "archived_by",
    )


@admin.register(Program)
class ProgramAdmin(PPAAdmin):
    list_display = ("title", "outcome_code", "status", "publication_status")
    list_filter = ("outcome_code", "publication_status", "status")


@admin.register(Project)
class ProjectAdmin(PPAAdmin):
    list_display = ("title", "program", "status", "publication_status")


@admin.register(SubProject)
class SubProjectAdmin(PPAAdmin):
    list_display = ("title", "project", "status", "publication_status")


@admin.register(Activity)
class ActivityAdmin(PPAAdmin):
    list_display = ("title", "activity_date", "status", "publication_status")


@admin.register(SupportingDocument)
class SupportingDocumentAdmin(admin.ModelAdmin):
    """
    The internal file is deliberately not a link here. An administrator who
    needs to read it goes through the review screen, where the access is
    logged against their name.
    """

    list_display = (
        "title", "kind", "risk_level", "status", "display_order", "uploaded_at",
    )
    list_filter = ("status", "risk_level", "kind", "is_image")
    search_fields = ("title", "description")
    readonly_fields = (
        "file", "public_file", "public_token", "internal_ref",
        "risk_level", "screened_at", "screening_findings", "screening_notes",
        "text_extracted", "size_bytes", "original_name", "is_image",
        "uploaded_at", "uploaded_by", "reviewed_at", "reviewed_by",
        "published_at", "published_by", "withdrawn_at", "withdrawn_by",
    )
