"""
Writing the e-SIRA audit trail.

Every action goes into `esira.AuditEntry`, the per-document trail shown on the
document page. The actions an administrator reading the system-wide log would
expect to find there - an upload, a signature, a routing, an approval or
rejection, a completion or cancellation, a certificate decision - are also
mirrored into `audit.AuditEvent`, so e-SIRA is not a blind spot in it.

Like the system log, writing an entry never fails the action being recorded.
"""

import logging

from audit.models import Action
from audit.recording import client_ip, get_request
from audit.recording import record as record_system

from .models import AuditAction, AuditEntry

logger = logging.getLogger("lgmed.esira")

# e-SIRA action -> system-wide audit action. Absent means not mirrored:
# views, downloads and box moves are detail for the document's own trail.
MIRRORED = {
    AuditAction.UPLOADED: Action.UPLOAD,
    AuditAction.SIGNED: Action.SIGN,
    AuditAction.SIGN_FAILED: Action.ACCESS_DENIED,
    AuditAction.ROUTED: Action.ROUTE,
    AuditAction.FORWARDED: Action.ROUTE,
    AuditAction.APPROVED: Action.APPROVE,
    AuditAction.REJECTED: Action.REJECT,
    AuditAction.COMPLETED: Action.COMPLETE,
    AuditAction.CANCELLED: Action.CANCEL,
    AuditAction.INTEGRITY_FAILURE: Action.ACCESS_DENIED,
    AuditAction.CERT_VERIFIED: Action.APPROVE,
    AuditAction.CERT_REJECTED: Action.REJECT,
    AuditAction.CERT_REVOKED: Action.DEACTIVATION,
}


def log(action, *, actor=None, document=None, detail="", version=None,
        metadata=None, request=None, target=None):
    """Record one e-SIRA action, and mirror it to the system log if it matters."""
    request = request or get_request()
    if actor is None and request is not None:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            actor = user

    entry = None
    try:
        entry = AuditEntry.objects.create(
            document=document,
            document_reference=(document.reference_no if document else ""),
            actor=actor,
            actor_label=(actor.get_display_name() if actor else "System")[:150],
            actor_role=(actor.get_role_display() if actor else "")[:40],
            action=action,
            detail=(detail or "")[:500],
            version_number=getattr(version, "number", None),
            metadata=metadata or {},
            ip_address=client_ip(request),
            user_agent=(
                request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""
            ),
        )
    except Exception:  # pragma: no cover - logging must never break a request
        logger.exception("Failed to write e-SIRA audit entry for %s", action)

    system_action = MIRRORED.get(action)
    if system_action:
        label = AuditAction(action).label
        record_system(
            system_action,
            target=target or document,
            detail=f"e-SIRA: {label}" + (f" - {detail}" if detail else ""),
            actor=actor,
            request=request,
        )
    return entry
