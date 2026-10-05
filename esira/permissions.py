"""
Who may do what to an e-SIRA document.

Role says what kind of work an account does; it does not say whose turn it is.
These rules combine the two, and they are the only place that decides - the
views ask here before showing a control, and `esira.workflow` asks again
before doing anything, so a crafted request is refused on the same terms as a
hidden button.

A recipient sees a document from the moment it is routed to them, not before:
the Regional Director does not need to read a draft three steps ahead of them.
"""

from django.db.models import Q

from .models import (
    OPEN_STEP_STATUSES,
    DocumentStatus,
    StepAction,
    StepStatus,
)

# Step states in which the recipient has been sent the document.
REACHED_STEP_STATUSES = [s for s in StepStatus.values if s != StepStatus.QUEUED]


def _active(user):
    return bool(user and user.is_authenticated and user.is_active)


def visible_documents(user):
    """The documents a user may open."""
    from .models import EsiraDocument

    if not _active(user):
        return EsiraDocument.objects.none()
    if user.can_oversee_esira:
        return EsiraDocument.objects.all()
    return EsiraDocument.objects.filter(
        Q(owner=user)
        | Q(steps__recipient=user, steps__status__in=REACHED_STEP_STATUSES)
    ).distinct()


def can_view(user, document):
    if not _active(user):
        return False
    if user.can_oversee_esira or document.owner_id == user.pk:
        return True
    return document.steps.filter(
        recipient=user, status__in=REACHED_STEP_STATUSES
    ).exists()


def is_owner(user, document):
    return _active(user) and document.owner_id == user.pk


def my_open_step(user, document):
    """The step waiting on this user right now, if it is their turn."""
    if not _active(user) or document.is_terminal:
        return None
    step = document.current_step()
    if step is not None and step.recipient_id == user.pk:
        return step
    return None


def can_self_sign(user, document):
    """
    An owner signing their own draft without routing it to anyone.

    Allowed only while every box on the document is theirs - a draft with a
    box for someone else must be routed so that person gets their turn.
    """
    if not (is_owner(user, document) and document.is_draft):
        return False
    boxes = document.boxes.filter(signature__isnull=True)
    return boxes.exists() and not boxes.exclude(signer=user).exists()


def can_sign(user, document):
    step = my_open_step(user, document)
    if step is not None:
        return step.action == StepAction.SIGN
    return can_self_sign(user, document)


def can_edit_boxes(user, document, signer=None):
    """
    Whether this user may add, move or remove unsigned boxes - for `signer`'s
    signature, when given.

    The owner prepares a draft: boxes for anyone. Once routed, only the
    person whose turn it is to sign may adjust their own boxes before signing.
    Nobody moves a box that has been signed, or anyone else's box mid-route.
    """
    if not _active(user) or document.is_terminal:
        return False
    if document.is_draft:
        return is_owner(user, document) and user.can_upload_esira
    step = my_open_step(user, document)
    if step is None or step.action != StepAction.SIGN:
        return False
    return signer is None or signer.pk == user.pk


def can_route(user, document):
    return (
        is_owner(user, document)
        and user.can_upload_esira
        and document.is_draft
    )


def can_act(user, document):
    """Approve, review or acknowledge - a step that is not a signature."""
    step = my_open_step(user, document)
    return step is not None and step.action != StepAction.SIGN


def can_reject(user, document):
    return my_open_step(user, document) is not None


def can_complete(user, document):
    return (
        _active(user)
        and document.status in (
            DocumentStatus.FULLY_SIGNED, DocumentStatus.ROUTING_COMPLETED,
        )
        and (is_owner(user, document) or user.can_oversee_esira)
    )


def can_cancel(user, document):
    return (
        _active(user)
        and not document.is_terminal
        and (is_owner(user, document) or user.can_oversee_esira)
    )


def can_view_audit(user, document):
    """The full trail - views and downloads included - is for the owner and overseers."""
    return is_owner(user, document) or (_active(user) and user.can_oversee_esira)


def has_open_step(step):
    return step is not None and step.status in OPEN_STEP_STATUSES
