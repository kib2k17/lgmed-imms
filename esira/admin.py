"""
Read-only in the Django admin.

Every change to an e-SIRA record goes through esira.workflow, which checks
permission and writes the audit trail. An admin form that edited a status or
a signature record directly would bypass both, so none is offered.
"""

from django.contrib import admin

from .models import (
    AuditEntry,
    DigitalSignature,
    DocumentVersion,
    EsiraDocument,
    RoutingStep,
    SignatureBox,
    SigningCertificate,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EsiraDocument)
class EsiraDocumentAdmin(ReadOnlyAdmin):
    list_display = ("reference_no", "title", "owner", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("reference_no", "title")


@admin.register(DocumentVersion)
class DocumentVersionAdmin(ReadOnlyAdmin):
    list_display = ("document", "number", "kind", "sha256", "created_at")


@admin.register(SignatureBox)
class SignatureBoxAdmin(ReadOnlyAdmin):
    list_display = ("document", "signer", "page", "signature")


@admin.register(RoutingStep)
class RoutingStepAdmin(ReadOnlyAdmin):
    list_display = ("document", "sequence", "recipient", "action", "status", "routed_at", "acted_at")
    list_filter = ("status", "action")


@admin.register(DigitalSignature)
class DigitalSignatureAdmin(ReadOnlyAdmin):
    list_display = ("document", "signer", "certificate_serial", "chain_trusted", "signed_at")


@admin.register(SigningCertificate)
class SigningCertificateAdmin(ReadOnlyAdmin):
    list_display = ("user", "subject_common_name", "issuer", "status", "not_after")
    list_filter = ("status",)


@admin.register(AuditEntry)
class AuditEntryAdmin(ReadOnlyAdmin):
    list_display = ("timestamp", "document_reference", "action", "actor_label")
    list_filter = ("action",)
