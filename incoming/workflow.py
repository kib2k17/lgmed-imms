"""
The transitions an incoming document may make, and what each one sets off.

Every change of hands goes through a function here rather than being written
into whichever view happened to need it. One function per transition means the
trail entry, the status change and the notification cannot drift apart - the
way they do when a second view is added later and remembers two of the three.

The rule the module exists for is enforced in `assign`: nothing may be given to
a focal person except by someone holding `can_review_incoming`, and the
document is stamped with who decided and when.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from notifications.models import Category, Level
from notifications.service import notify, resolve

from .models import EventType, IncomingDocument, IncomingStatus


# ---------------------------------------------------------------------------
# Audiences
# ---------------------------------------------------------------------------


def division_chiefs():
    """Those who may review and assign - the Chief and designated administrators."""
    from accounts.capabilities import users_with

    return users_with("can_review_incoming")


def focal_persons():
    """Accounts a document may be assigned to."""
    from accounts.capabilities import users_with

    return users_with("can_encode")


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


def log(document, actor, event_type, *, detail="", notes="", from_status="",
        to_status=""):
    """Write one entry in the document's own trail."""
    from .models import IncomingEvent

    return IncomingEvent.objects.create(
        document=document,
        actor=actor if actor is not None and actor.is_authenticated else None,
        actor_label=(
            actor.get_display_name()
            if actor is not None and actor.is_authenticated
            else "System"
        ),
        actor_role=(
            actor.get_role_display()
            if actor is not None and actor.is_authenticated
            else ""
        ),
        event_type=event_type,
        detail=detail[:255],
        notes=notes,
        from_status=from_status,
        to_status=to_status,
    )


# ---------------------------------------------------------------------------
# Notification keys
#
# One key per standing condition, so a document that has waited three weeks
# produces one notice rather than twenty-one.
# ---------------------------------------------------------------------------


def review_key(document):
    return f"incoming:review:{document.pk}"


def assignment_key(document):
    return f"incoming:assigned:{document.pk}"


def acknowledgement_key(document):
    return f"incoming:acknowledge:{document.pk}"


def overdue_key(document):
    return f"incoming:overdue:{document.pk}"


def silence_key(document):
    return f"incoming:silent:{document.pk}"


def _clear_open_conditions(document):
    """Withdraw every standing notice about a document that is now finished."""
    for key in (
        review_key(document),
        assignment_key(document),
        acknowledgement_key(document),
        overdue_key(document),
        silence_key(document),
    ):
        resolve(key)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


@transaction.atomic
def record_received(document, actor):
    """
    An encoder has recorded a document that arrived.

    It is deliberately left unassigned: the Chief decides who handles it.
    """
    log(
        document,
        actor,
        EventType.RECORDED,
        detail=f"Received from {document.source_office}",
        notes=document.initial_remarks,
        to_status=document.status,
    )
    notify(
        division_chiefs(),
        title=f"Incoming document for review: {document.docket_number}",
        message=f"{document.subject} - from {document.source_office}",
        url=document.get_absolute_url(),
        category=Category.REVIEW,
        level=Level.ACTION,
        dedupe_key=review_key(document),
        exclude=actor,
    )
    return document


@transaction.atomic
def record_amended(document, actor, changes=""):
    """An encoder has corrected a record that has not yet been assigned."""
    log(
        document,
        actor,
        EventType.EDITED,
        detail=changes or "Record details amended",
        to_status=document.status,
    )
    return document


@transaction.atomic
def review(document, actor, notes):
    """
    The Chief has read the document and noted what it requires.

    Reviewing does not move the document on by itself - a note may be made
    today and the focal person chosen tomorrow - but it stamps the record with
    who read it and when, which is the point of the step.
    """
    if not getattr(actor, "can_review_incoming", False):
        raise PermissionDenied("Only the Division Chief may review incoming documents.")

    document.review_notes = notes
    document.reviewed_by = actor
    document.reviewed_at = timezone.now()
    document.save(update_fields=["review_notes", "reviewed_by", "reviewed_at",
                                "updated_at"])

    log(
        document,
        actor,
        EventType.REVIEWED,
        detail="Reviewed and noted",
        notes=notes,
        to_status=document.status,
    )
    if document.assigned_to_id:
        notify(
            [document.assigned_to],
            title=f"Instruction updated: {document.docket_number}",
            message=(notes or document.subject)[:400],
            url=document.get_absolute_url(),
            category=Category.ASSIGNMENT,
            level=Level.ACTION,
            dedupe_key=f"incoming:note:{document.pk}:{document.reviewed_at:%Y%m%d%H%M}",
            exclude=actor,
        )
    return document


@transaction.atomic
def assign(document, actor, *, assignee, remarks="", priority=None, due_date=None,
           notes=None):
    """
    The Chief names the focal person. This is the only route to an assignment.

    Reviewing is implied: a Chief who assigns has, by definition, read the
    document, so a record that was assigned without a separate review step is
    still stamped as reviewed rather than left looking unread.
    """
    if not getattr(actor, "can_review_incoming", False):
        raise PermissionDenied("Only the Division Chief may assign incoming documents.")

    previous = document.assigned_to
    from_status = document.status

    if notes is not None:
        document.review_notes = notes
    if document.reviewed_at is None:
        document.reviewed_by = actor
        document.reviewed_at = timezone.now()

    document.assigned_to = assignee
    document.assigned_by = actor
    document.assigned_at = timezone.now()
    document.assignment_remarks = remarks
    if priority:
        document.priority = priority
    document.due_date = due_date
    document.status = IncomingStatus.ASSIGNED
    document.acknowledged_at = None
    document.save()

    reassigned = previous is not None and previous != assignee
    log(
        document,
        actor,
        EventType.REASSIGNED if reassigned else EventType.ASSIGNED,
        detail=(
            f"Reassigned from {previous.get_display_name()} to "
            f"{assignee.get_display_name()}"
            if reassigned
            else f"Assigned to {assignee.get_display_name()}"
        ),
        notes=remarks,
        from_status=from_status,
        to_status=document.status,
    )

    # The document is no longer waiting on the Chief.
    resolve(review_key(document))
    if reassigned:
        resolve(assignment_key(document))
        resolve(acknowledgement_key(document))

    notify(
        [assignee],
        title=f"Document assigned to you: {document.docket_number}",
        message=(remarks or document.subject)[:400],
        url=document.get_absolute_url(),
        category=Category.ASSIGNMENT,
        level=Level.URGENT if document.priority == "URGENT" else Level.ACTION,
        dedupe_key=assignment_key(document),
        exclude=actor,
    )
    return document


@transaction.atomic
def acknowledge(document, actor):
    """The focal person confirms they have received the assignment."""
    if not document.may_be_acknowledged_by(actor):
        raise PermissionDenied(
            "Only the focal person this document is assigned to may acknowledge it."
        )

    from_status = document.status
    document.acknowledged_at = timezone.now()
    document.status = IncomingStatus.ACKNOWLEDGED
    document.save(update_fields=["acknowledged_at", "status", "updated_at"])

    log(
        document,
        actor,
        EventType.ACKNOWLEDGED,
        detail="Assignment acknowledged",
        from_status=from_status,
        to_status=document.status,
    )
    resolve(acknowledgement_key(document))

    recipients = list(division_chiefs())
    if document.assigned_by and document.assigned_by not in recipients:
        recipients.append(document.assigned_by)
    notify(
        recipients,
        title=f"Assignment acknowledged: {document.docket_number}",
        message=f"{actor.get_display_name()} acknowledged {document.subject}",
        url=document.get_absolute_url(),
        category=Category.ASSIGNMENT,
        level=Level.INFO,
        dedupe_key=f"incoming:acknowledged:{document.pk}",
        exclude=actor,
    )
    return document


@transaction.atomic
def add_update(document, actor, update):
    """
    Record what the focal person has done, and move the document with it.

    The status the officer reports on the update becomes the document's status:
    the update *is* the status change, and asking for both separately is how a
    record ends up saying "In progress" three weeks after it was finished.
    """
    if not document.may_be_updated_by(actor):
        raise PermissionDenied(
            "Only the assigned focal person may provide updates on this document."
        )

    from_status = document.status
    update.document = document
    update.created_by = actor
    update.save()

    document.status = update.status
    if update.status == IncomingStatus.COMPLETED:
        document.completed_at = document.completed_at or timezone.now()
    else:
        document.completed_at = None
    document.save(update_fields=["status", "completed_at", "updated_at"])

    completed = update.status == IncomingStatus.COMPLETED
    log(
        document,
        actor,
        EventType.COMPLETED if completed else EventType.UPDATED,
        detail=update.action_taken[:255],
        notes=update.remarks,
        from_status=from_status,
        to_status=document.status,
    )

    resolve(silence_key(document))
    if completed:
        _clear_open_conditions(document)

    notify(
        division_chiefs(),
        title=(
            f"Document completed: {document.docket_number}"
            if completed
            else f"Update on {document.docket_number}"
        ),
        message=f"{actor.get_display_name()}: {update.action_taken}"[:400],
        url=document.get_absolute_url(),
        category=Category.ASSIGNMENT,
        level=Level.INFO,
        dedupe_key=f"incoming:update:{update.pk}",
        exclude=actor,
    )
    return document


@transaction.atomic
def return_for_revision(document, actor, remarks):
    """The Chief sends the work back to the focal person with what is wanted."""
    if not getattr(actor, "can_review_incoming", False):
        raise PermissionDenied("Only the Division Chief may return a document.")
    if not document.is_assigned:
        raise PermissionDenied("A document that has not been assigned cannot be returned.")

    from_status = document.status
    document.status = IncomingStatus.RETURNED
    document.completed_at = None
    document.save(update_fields=["status", "completed_at", "updated_at"])

    log(
        document,
        actor,
        EventType.RETURNED,
        detail="Returned for revision",
        notes=remarks,
        from_status=from_status,
        to_status=document.status,
    )
    notify(
        [document.assigned_to],
        title=f"Returned for revision: {document.docket_number}",
        message=(remarks or document.subject)[:400],
        url=document.get_absolute_url(),
        category=Category.ASSIGNMENT,
        level=Level.ACTION,
        dedupe_key=f"incoming:returned:{document.pk}:{timezone.now():%Y%m%d%H%M}",
        exclude=actor,
    )
    return document


# ---------------------------------------------------------------------------
# Standing conditions
#
# Nothing "happens" on the day a document becomes overdue, so these are found
# on a schedule rather than raised by an event. Called from
# `notifications.service.refresh_standing_notices`.
# ---------------------------------------------------------------------------


def refresh_standing_notices():
    """Tell the people who can act about incoming work that is waiting."""
    from notifications.models import Notification

    today = timezone.localdate()
    raised = 0
    live = set()

    chiefs = list(division_chiefs())

    # -- waiting on the Chief to review and assign ------------------------
    for document in IncomingDocument.objects.for_review():
        key = review_key(document)
        live.add(key)
        waiting = (today - document.date_received).days
        raised += len(
            notify(
                chiefs,
                title=f"Incoming document awaiting review: {document.docket_number}",
                message=(
                    f"{document.subject} - received "
                    f"{document.date_received:%d %b %Y}"
                    + (f", {waiting} days ago" if waiting > 0 else "")
                ),
                url=document.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.URGENT if waiting > 3 else Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- assigned but not yet acknowledged ---------------------------------
    for document in IncomingDocument.objects.awaiting_acknowledgement().select_related(
        "assigned_to"
    ):
        if not document.assigned_to:
            continue
        key = acknowledgement_key(document)
        live.add(key)
        raised += len(
            notify(
                [document.assigned_to],
                title=f"Acknowledge your assignment: {document.docket_number}",
                message=f"{document.subject} - assigned {document.assigned_at:%d %b %Y}",
                url=document.get_absolute_url(),
                category=Category.ASSIGNMENT,
                level=Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- past the action due date ------------------------------------------
    for document in IncomingDocument.objects.overdue(today).select_related("assigned_to"):
        key = overdue_key(document)
        live.add(key)
        days = document.days_overdue
        audience = list(chiefs)
        if document.assigned_to and document.assigned_to not in audience:
            audience.append(document.assigned_to)
        raised += len(
            notify(
                audience,
                title=f"Incoming document overdue: {document.docket_number}",
                message=(
                    f"{document.subject} - was due {document.due_date:%d %b %Y}, "
                    f"{days} day{'s' if days != 1 else ''} ago"
                ),
                url=document.get_absolute_url(),
                category=Category.OVERDUE,
                level=Level.URGENT if days > 7 else Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- assigned, unfinished, and nothing heard ---------------------------
    for document in IncomingDocument.objects.awaiting_update().select_related(
        "assigned_to"
    ):
        if not document.assigned_to:
            continue
        key = silence_key(document)
        live.add(key)
        days = document.days_since_last_update or 0
        audience = list(chiefs)
        if document.assigned_to not in audience:
            audience.append(document.assigned_to)
        raised += len(
            notify(
                audience,
                title=f"Update awaited: {document.docket_number}",
                message=(
                    f"{document.subject} - no update for "
                    f"{days} day{'s' if days != 1 else ''}"
                ),
                url=document.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.ACTION,
                dedupe_key=key,
            )
        )

    stale = (
        Notification.objects.filter(dismissed_at__isnull=True)
        .filter(dedupe_key__startswith="incoming:")
        .exclude(dedupe_key__in=live)
        # Event notices - assigned to you, returned to you, an update was
        # posted - report something that happened once. They are not standing
        # conditions and must not be withdrawn here.
        .exclude(dedupe_key__startswith="incoming:assigned:")
        .exclude(dedupe_key__startswith="incoming:acknowledged:")
        .exclude(dedupe_key__startswith="incoming:returned:")
        .exclude(dedupe_key__startswith="incoming:update:")
        .exclude(dedupe_key__startswith="incoming:note:")
    )
    withdrawn = stale.update(dismissed_at=timezone.now(), read_at=timezone.now())
    return {"raised": raised, "withdrawn": withdrawn}
