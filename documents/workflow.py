"""
The transitions a document may make, and what each one sets off.

Every change of state goes through a function here rather than being written
into whichever view happened to need it. One function per transition means the
trail entry, the status change and the notification cannot drift apart - the
way they do when a second view is added later and remembers two of the three.

Nothing in `documents.views` decides who may do what. Each function below
re-checks the permission itself and raises `PermissionDenied`, so an action
taken through the shell or a management command is refused on the same terms
as one taken through a button.
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from notifications.models import Category, Level
from notifications.service import notify, resolve

from .models import (
    Document,
    DocumentEvent,
    DocumentStatus,
    EventType,
    RetentionAction,
    RetentionDisposition,
)

# How long a "viewed" entry stands for. Writing a row every time someone opens
# a record would bury the trail in noise and make it useless for the thing it
# exists for; one entry per person per day answers "who has seen this?" without
# drowning the acts that actually changed something.
VIEW_DEDUPE_HOURS = 24


# ---------------------------------------------------------------------------
# Audiences
# ---------------------------------------------------------------------------


def assigners():
    """Those who may name a focal person - the Chief and administrators."""
    from accounts.capabilities import users_with

    return users_with("can_assign_documents")


def records_officers():
    """Those who archive, restore and set retention."""
    from accounts.capabilities import users_with

    return users_with("can_archive_documents")


def focal_persons():
    """Accounts a document may be assigned to."""
    from accounts.capabilities import users_with

    return users_with("can_encode")


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


def log(document, actor, event_type, *, detail="", notes="", from_status="",
        to_status="", request=None):
    """Write one entry in the document's own trail."""
    authenticated = actor is not None and getattr(actor, "is_authenticated", False)
    ip = None
    if request is not None:
        from audit.recording import client_ip

        ip = client_ip(request)

    return DocumentEvent.objects.create(
        document=document,
        actor=actor if authenticated else None,
        actor_label=actor.get_display_name() if authenticated else "System",
        actor_role=actor.get_role_display() if authenticated else "",
        event_type=event_type,
        detail=detail[:255],
        notes=notes,
        from_status=from_status,
        to_status=to_status,
        ip_address=ip,
    )


def record_view(document, actor, request=None):
    """
    Note that someone opened the record, at most once a day per person.

    Returns the entry written, or None where one already stands. See
    `VIEW_DEDUPE_HOURS`.
    """
    if not getattr(actor, "is_authenticated", False):
        return None

    since = timezone.now() - timedelta(hours=VIEW_DEDUPE_HOURS)
    already = DocumentEvent.objects.filter(
        document=document,
        actor=actor,
        event_type=EventType.VIEWED,
        occurred_at__gte=since,
    ).exists()
    if already:
        return None
    return log(document, actor, EventType.VIEWED, detail="Record opened",
               request=request)


def record_download(document, actor, *, version=None, request=None):
    """Note a file leaving the system. Never deduplicated."""
    if version is not None:
        detail = f"Downloaded version {version.version_number} ({version.file_name})"
    else:
        detail = f"Downloaded {document.file_name}"
    return log(document, actor, EventType.DOWNLOADED, detail=detail, request=request)


# ---------------------------------------------------------------------------
# Notification keys
#
# One key per standing condition, so a document that has waited three weeks
# produces one notice rather than twenty-one.
# ---------------------------------------------------------------------------


def review_key(document):
    return f"documents:review:{document.pk}"


def assignment_key(document):
    return f"documents:assigned:{document.pk}"


def approval_key(document):
    return f"documents:approval:{document.pk}"


def overdue_key(document):
    return f"documents:overdue:{document.pk}"


def retention_key(document):
    return f"documents:retention:{document.pk}"


def _clear_open_conditions(document):
    """Withdraw every standing notice about a document that is now finished."""
    for key in (
        review_key(document),
        assignment_key(document),
        approval_key(document),
        overdue_key(document),
    ):
        resolve(key)


# ---------------------------------------------------------------------------
# Registration and amendment
# ---------------------------------------------------------------------------


@transaction.atomic
def register(document, actor, *, request=None):
    """
    A document has been recorded in the register.

    Where a file came with it, that file becomes version 1 straight away - a
    document management system in which the first upload is not a version has
    a version history that starts by lying about its own beginning.
    """
    log(
        document,
        actor,
        EventType.REGISTERED,
        detail=(
            f"Registered as {document.reference_number}"
            + (f", received from {document.sender}" if document.sender else "")
        ),
        notes=document.remarks,
        to_status=document.status,
        request=request,
    )

    if document.file and not document.versions.exists():
        document.adopt_current_file(user=actor, reason="Initial upload")
        log(
            document,
            actor,
            EventType.UPLOADED,
            detail=f"Version 1 uploaded ({document.file_name})",
            request=request,
        )

    if document.status == DocumentStatus.FOR_REVIEW:
        _notify_for_review(document, actor)
    return document


@transaction.atomic
def amend(document, actor, *, changes="", request=None):
    """The details of a record have been corrected."""
    if not document.may_be_edited_by(actor):
        raise PermissionDenied(
            "Your role does not permit you to edit this document."
        )
    log(
        document,
        actor,
        EventType.EDITED,
        detail=changes or "Record details amended",
        to_status=document.status,
        request=request,
    )
    return document


@transaction.atomic
def upload_version(document, actor, *, uploaded_file=None, reason, adopt=False,
                   request=None):
    """
    Supersede the document's file, keeping the one it had.

    A reason is required rather than optional: the version history exists to
    answer "why did this change?", and a stack of files with no explanation
    answers only "it did".
    """
    if not document.may_upload_version_by(actor):
        raise PermissionDenied(
            "Your role does not permit you to upload a new version of this document."
        )

    previous = document.next_version_number() - 1
    if adopt:
        # The file is already stored - a form saved it before we got here.
        version = document.adopt_current_file(user=actor, reason=reason)
    else:
        version = document.add_version(uploaded_file, user=actor, reason=reason)
    log(
        document,
        actor,
        EventType.VERSION_UPLOADED,
        detail=(
            f"Version {version.version_number} uploaded ({version.file_name})"
            + (f", superseding version {previous}" if previous >= 1 else "")
        ),
        notes=reason,
        to_status=document.status,
        request=request,
    )

    audience = []
    if document.owner_id and document.owner != actor:
        audience.append(document.owner)
    if document.assigned_to_id and document.assigned_to not in audience:
        audience.append(document.assigned_to)
    notify(
        audience,
        title=f"New version of {document.reference_number}",
        message=f"{document.title} - version {version.version_number}: {reason}"[:400],
        url=document.get_absolute_url(),
        category=Category.ASSIGNMENT,
        level=Level.INFO,
        dedupe_key=f"documents:version:{version.pk}",
        exclude=actor,
    )
    return version


# ---------------------------------------------------------------------------
# Movement through the lifecycle
# ---------------------------------------------------------------------------


def _refuse_if_synced(document):
    """
    An entry mirroring an incoming document moves only with that document.

    See `incoming.register`. Archive, retention and disposal are not refused:
    they are the register's own business once the work is done.
    """
    if document.is_synced:
        raise PermissionDenied(
            "This document is managed through Incoming and Outgoing Monitoring. "
            "Take the action there; the register follows."
        )


def _move(document, actor, to_status, *, detail, notes="", request=None,
          extra_fields=()):
    """Change status, stamp the record and write the trail entry, once."""
    _refuse_if_synced(document)
    from_status = document.status
    document.status = to_status
    document.save(update_fields=["status", "updated_at", *extra_fields])
    log(
        document,
        actor,
        EventType.STATUS_CHANGED,
        detail=detail,
        notes=notes,
        from_status=from_status,
        to_status=to_status,
        request=request,
    )
    return document


def _notify_for_review(document, actor=None):
    notify(
        records_officers(),
        title=f"Document for review: {document.reference_number}",
        message=f"{document.title} - {document.subject or document.get_status_display()}"[:400],
        url=document.get_absolute_url(),
        category=Category.REVIEW,
        level=Level.ACTION,
        dedupe_key=review_key(document),
        exclude=actor,
    )


@transaction.atomic
def submit_for_review(document, actor, *, notes="", request=None):
    """A draft or newly received document is put up for review."""
    if not document.may_be_edited_by(actor):
        raise PermissionDenied("Your role does not permit you to move this document.")
    _move(document, actor, DocumentStatus.FOR_REVIEW,
          detail="Submitted for review", notes=notes, request=request)
    _notify_for_review(document, actor)
    return document


@transaction.atomic
def review(document, actor, *, notes="", request=None):
    """
    The document has been read and noted, and now awaits a focal person.

    Reviewing stamps who read it and when; naming the person who will act on
    it is a separate decision, and a separate capability.
    """
    if not getattr(actor, "can_archive_documents", False) and not getattr(
        actor, "can_assign_documents", False
    ):
        raise PermissionDenied("Your role does not permit you to review documents.")

    document.reviewed_by = actor
    document.reviewed_at = timezone.now()
    document.review_notes = notes
    _move(
        document,
        actor,
        DocumentStatus.FOR_ASSIGNMENT,
        detail="Reviewed - awaiting assignment",
        notes=notes,
        request=request,
        extra_fields=("reviewed_by", "reviewed_at", "review_notes"),
    )
    resolve(review_key(document))
    notify(
        assigners(),
        title=f"Document awaiting assignment: {document.reference_number}",
        message=f"{document.title} - reviewed by {actor.get_display_name()}"[:400],
        url=document.get_absolute_url(),
        category=Category.REVIEW,
        level=Level.ACTION,
        dedupe_key=assignment_key(document),
        exclude=actor,
    )
    return document


@transaction.atomic
def assign(document, actor, *, assignee, remarks="", due_date=None, request=None):
    """
    Name the focal person. This is the only route to an assignment.

    Reviewing is implied: someone who assigns has, by definition, read the
    document, so a record assigned without a separate review step is still
    stamped as reviewed rather than left looking unread.
    """
    if not document.may_be_assigned_by(actor):
        raise PermissionDenied(
            "Only the Division Chief may assign a document to a focal person."
        )

    previous = document.assigned_to
    reassigned = previous is not None and previous != assignee

    if document.reviewed_at is None:
        document.reviewed_by = actor
        document.reviewed_at = timezone.now()
    document.assigned_to = assignee
    document.assigned_by = actor
    document.assigned_at = timezone.now()
    document.assignment_remarks = remarks
    document.due_date = due_date

    from_status = document.status
    document.status = DocumentStatus.ASSIGNED
    document.save()

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
        request=request,
    )

    resolve(review_key(document))
    if reassigned:
        resolve(assignment_key(document))

    notify(
        [assignee],
        title=f"Document assigned to you: {document.reference_number}",
        message=(remarks or document.title)[:400],
        url=document.get_absolute_url(),
        category=Category.ASSIGNMENT,
        level=Level.ACTION,
        dedupe_key=assignment_key(document),
        exclude=actor,
    )
    return document


@transaction.atomic
def start_processing(document, actor, *, notes="", request=None):
    """The focal person has begun work."""
    if not document.may_be_edited_by(actor):
        raise PermissionDenied("Your role does not permit you to move this document.")
    return _move(document, actor, DocumentStatus.IN_PROGRESS,
                 detail="Processing started", notes=notes, request=request)


@transaction.atomic
def submit_for_approval(document, actor, *, notes="", request=None):
    """The work is done and awaits sign-off."""
    if not document.may_be_edited_by(actor):
        raise PermissionDenied("Your role does not permit you to move this document.")
    _move(document, actor, DocumentStatus.FOR_APPROVAL,
          detail="Submitted for approval", notes=notes, request=request)
    notify(
        records_officers(),
        title=f"Document awaiting approval: {document.reference_number}",
        message=f"{document.title} - from {actor.get_display_name()}"[:400],
        url=document.get_absolute_url(),
        category=Category.REVIEW,
        level=Level.ACTION,
        dedupe_key=approval_key(document),
        exclude=actor,
    )
    return document


@transaction.atomic
def complete(document, actor, *, notes="", request=None):
    """
    Sign the document off, and start its retention clock.

    Completion is where retention begins, so the period is worked out here
    from the document type rather than being left for someone to remember. A
    type carrying no period leaves `retention_until` unset and the document
    shows as having no policy - which is a visible gap the records officer can
    close, rather than an invisible one.
    """
    if not getattr(actor, "can_approve", False):
        raise PermissionDenied("Your role does not permit you to approve documents.")
    _refuse_if_synced(document)

    now = timezone.now()
    document.approved_by = actor
    document.approved_at = now
    document.completed_at = now

    today = timezone.localdate()
    if document.retention_until is None:
        document.retention_until = document.computed_retention_until(today)
    if document.document_type.retention_action == RetentionAction.PERMANENT:
        document.retention_disposition = RetentionDisposition.PERMANENT

    from_status = document.status
    document.status = DocumentStatus.COMPLETED
    document.save()

    log(
        document,
        actor,
        EventType.APPROVED,
        detail=(
            "Approved and completed"
            + (
                f" - retained until {document.retention_until:%d %b %Y}"
                if document.retention_until
                else " - no retention period set for this document type"
            )
        ),
        notes=notes,
        from_status=from_status,
        to_status=document.status,
        request=request,
    )
    _clear_open_conditions(document)

    audience = []
    if document.owner_id and document.owner != actor:
        audience.append(document.owner)
    if document.assigned_to_id and document.assigned_to not in audience:
        audience.append(document.assigned_to)
    notify(
        audience,
        title=f"Document completed: {document.reference_number}",
        message=f"{document.title} - approved by {actor.get_display_name()}"[:400],
        url=document.get_absolute_url(),
        category=Category.ASSIGNMENT,
        level=Level.INFO,
        dedupe_key=f"documents:completed:{document.pk}",
        exclude=actor,
    )
    return document


@transaction.atomic
def cancel(document, actor, *, reason, request=None):
    """Stop a document that will not be carried through."""
    if not getattr(actor, "can_approve", False) and not document.is_responsible(actor):
        raise PermissionDenied(
            "Your role does not permit you to cancel this document."
        )
    if document.is_archived or document.is_disposed:
        raise PermissionDenied("An archived document cannot be cancelled.")

    _move(document, actor, DocumentStatus.CANCELLED,
          detail="Cancelled", notes=reason, request=request)
    log(document, actor, EventType.CANCELLED, detail=reason[:255], request=request)
    _clear_open_conditions(document)
    return document


# ---------------------------------------------------------------------------
# Retention, archiving and disposal
# ---------------------------------------------------------------------------


@transaction.atomic
def set_retention(document, actor, *, retention_until=None, disposition=None,
                  notes="", request=None):
    """Record the records officer's decision about a document's long-term fate."""
    if not getattr(actor, "can_archive_documents", False):
        raise PermissionDenied(
            "Your role does not permit you to set a retention period."
        )

    previous = document.get_retention_disposition_display()
    document.retention_until = retention_until
    if disposition:
        document.retention_disposition = disposition
    document.retention_notes = notes
    document.retention_reviewed_by = actor
    document.retention_reviewed_at = timezone.now()
    document.save(
        update_fields=[
            "retention_until", "retention_disposition", "retention_notes",
            "retention_reviewed_by", "retention_reviewed_at", "updated_at",
        ]
    )

    log(
        document,
        actor,
        EventType.RETENTION_SET,
        detail=(
            f"Retention decision: {previous} -> "
            f"{document.get_retention_disposition_display()}"
            + (
                f", until {document.retention_until:%d %b %Y}"
                if document.retention_until
                else ""
            )
        ),
        notes=notes,
        request=request,
    )
    if not document.is_retention_due:
        resolve(retention_key(document))

    if document.retention_disposition == RetentionDisposition.FOR_DISPOSAL:
        from accounts.capabilities import users_with

        notify(
            users_with("can_dispose_documents"),
            title=f"Document marked for disposal: {document.reference_number}",
            message=f"{document.title} - awaiting disposal authority"[:400],
            url=document.get_absolute_url(),
            category=Category.REVIEW,
            level=Level.ACTION,
            dedupe_key=f"documents:disposal:{document.pk}",
            exclude=actor,
        )
    return document


@transaction.atomic
def archive(document, actor, *, reason="", request=None):
    """
    Move a finished document out of circulation, keeping everything about it.

    Nothing is removed: the metadata, the ownership, every version and the
    whole trail stay exactly as they were. What changes is who may reach it -
    see `Document.may_be_viewed_by`.
    """
    if not document.may_be_archived_by(actor):
        raise PermissionDenied(
            "Only a completed or cancelled document may be archived, and only "
            "by a records officer."
        )

    document.archived_by = actor
    document.archived_at = timezone.now()
    document.archive_reason = reason
    # A document may not sit on the public website once it has left
    # circulation; archiving it and leaving it published is a contradiction
    # the public would be the last to notice.
    document.is_public = False
    if document.retention_until is None:
        document.retention_until = document.computed_retention_until(
            timezone.localdate()
        )

    from_status = document.status
    document.status = DocumentStatus.ARCHIVED
    document.save()

    log(
        document,
        actor,
        EventType.ARCHIVED,
        detail=(
            "Archived"
            + (
                f" - retained until {document.retention_until:%d %b %Y}"
                if document.retention_until
                else ""
            )
        ),
        notes=reason,
        from_status=from_status,
        to_status=document.status,
        request=request,
    )
    _clear_open_conditions(document)
    return document


@transaction.atomic
def restore(document, actor, *, reason="", request=None):
    """Bring an archived document back into circulation."""
    if not document.may_be_restored_by(actor):
        raise PermissionDenied(
            "Your role does not permit you to restore an archived document."
        )

    document.archived_by = None
    document.archived_at = None
    document.archive_reason = ""

    from_status = document.status
    # It goes back to where it was when it left: finished, but live again.
    document.status = DocumentStatus.COMPLETED
    document.save()

    log(
        document,
        actor,
        EventType.RESTORED,
        detail="Restored from the archive",
        notes=reason,
        from_status=from_status,
        to_status=document.status,
        request=request,
    )
    notify(
        records_officers(),
        title=f"Document restored: {document.reference_number}",
        message=f"{document.title} - restored by {actor.get_display_name()}"[:400],
        url=document.get_absolute_url(),
        category=Category.SYSTEM,
        level=Level.INFO,
        dedupe_key=f"documents:restored:{document.pk}:{timezone.now():%Y%m%d%H%M}",
        exclude=actor,
    )
    return document


@transaction.atomic
def dispose(document, actor, *, authority, notes="", delete_file=True,
            request=None):
    """
    Permanently dispose of an archived document, under a written authority.

    The file goes; the record does not. What survives is the metadata, the
    ownership, the version history as a list of what once existed, and the
    complete trail ending in this entry - which is precisely what a disposal
    has to be able to prove afterwards.
    """
    if not document.may_be_disposed_by(actor):
        raise PermissionDenied(
            "A document may only be disposed of when it is archived, marked "
            "for disposal, and by an officer authorised to dispose."
        )
    if authority is None:
        raise PermissionDenied(
            "A disposal authority must be cited before a document is disposed of."
        )

    removed = []
    if delete_file:
        for version in document.versions.all():
            if version.file:
                removed.append(version.file.name)
                version.file.delete(save=False)
                version.save(update_fields=["file"])
        if document.file:
            document.file.delete(save=False)
        for supporting in document.supporting_files.all():
            if supporting.file:
                removed.append(supporting.file.name)
                supporting.file.delete(save=False)
                supporting.save(update_fields=["file"])

    document.disposed_by = actor
    document.disposed_at = timezone.now()
    document.disposal_authority = authority
    document.disposal_notes = notes
    document.retention_disposition = RetentionDisposition.DISPOSED
    document.is_public = False
    document.save()

    log(
        document,
        actor,
        EventType.DISPOSED,
        detail=(
            f"Disposed under {authority.reference}"
            + (f"; {len(removed)} file(s) destroyed" if removed else "")
        ),
        notes=notes,
        to_status=document.status,
        request=request,
    )
    resolve(retention_key(document))
    resolve(f"documents:disposal:{document.pk}")

    notify(
        records_officers(),
        title=f"Document disposed: {document.reference_number}",
        message=(
            f"{document.title} - disposed under {authority.reference} by "
            f"{actor.get_display_name()}"
        )[:400],
        url=document.get_absolute_url(),
        category=Category.SYSTEM,
        level=Level.INFO,
        dedupe_key=f"documents:disposed:{document.pk}",
        exclude=actor,
    )
    return document


# ---------------------------------------------------------------------------
# Standing conditions
#
# Nothing "happens" on the day a document becomes overdue or its retention
# period runs out, so these are found on a schedule rather than raised by an
# event. Called from `notifications.service.refresh_standing_notices`.
# ---------------------------------------------------------------------------


def refresh_standing_notices():
    """Tell the people who can act about document work that is waiting."""
    from notifications.models import Notification

    today = timezone.localdate()
    raised = 0
    live = set()

    officers = list(records_officers())
    chiefs = list(assigners())

    # -- waiting to be reviewed -------------------------------------------
    for document in Document.objects.filter(status=DocumentStatus.FOR_REVIEW):
        key = review_key(document)
        live.add(key)
        raised += len(
            notify(
                officers,
                title=f"Document awaiting review: {document.reference_number}",
                message=f"{document.title} - {document.subject}"[:400],
                url=document.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- reviewed, but nobody has been named yet ---------------------------
    for document in Document.objects.filter(status=DocumentStatus.FOR_ASSIGNMENT):
        key = assignment_key(document)
        live.add(key)
        raised += len(
            notify(
                chiefs,
                title=f"Document awaiting assignment: {document.reference_number}",
                message=f"{document.title} - {document.subject}"[:400],
                url=document.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- work finished, sign-off outstanding -------------------------------
    for document in Document.objects.filter(status=DocumentStatus.FOR_APPROVAL):
        key = approval_key(document)
        live.add(key)
        raised += len(
            notify(
                officers,
                title=f"Document awaiting approval: {document.reference_number}",
                message=f"{document.title} - {document.subject}"[:400],
                url=document.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- past the action due date ------------------------------------------
    for document in Document.objects.overdue(today).select_related("assigned_to", "owner"):
        key = overdue_key(document)
        live.add(key)
        days = document.days_overdue
        audience = list(chiefs)
        for person in (document.assigned_to, document.owner):
            if person and person not in audience:
                audience.append(person)
        raised += len(
            notify(
                audience,
                title=f"Document overdue: {document.reference_number}",
                message=(
                    f"{document.title} - was due {document.due_date:%d %b %Y}, "
                    f"{days} day{'s' if days != 1 else ''} ago"
                )[:400],
                url=document.get_absolute_url(),
                category=Category.OVERDUE,
                level=Level.URGENT if days > 7 else Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- retention period run out, or about to -----------------------------
    for document in Document.objects.retention_due(today):
        key = retention_key(document)
        live.add(key)
        raised += len(
            notify(
                officers,
                title=f"Retention review due: {document.reference_number}",
                message=(
                    f"{document.title} - retention ended "
                    f"{document.retention_until:%d %b %Y}"
                )[:400],
                url=document.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.ACTION,
                dedupe_key=key,
            )
        )

    for document in Document.objects.retention_approaching(today=today):
        key = retention_key(document)
        live.add(key)
        raised += len(
            notify(
                officers,
                title=f"Retention approaching: {document.reference_number}",
                message=(
                    f"{document.title} - retention ends "
                    f"{document.retention_until:%d %b %Y}"
                )[:400],
                url=document.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.INFO,
                dedupe_key=key,
            )
        )

    stale = (
        Notification.objects.filter(dismissed_at__isnull=True)
        .filter(dedupe_key__startswith="documents:")
        .exclude(dedupe_key__in=live)
        # Event notices - assigned to you, a version was uploaded, a document
        # was disposed of - report something that happened once. They are not
        # standing conditions and must not be withdrawn here.
        .exclude(dedupe_key__startswith="documents:assigned:")
        .exclude(dedupe_key__startswith="documents:version:")
        .exclude(dedupe_key__startswith="documents:completed:")
        .exclude(dedupe_key__startswith="documents:restored:")
        .exclude(dedupe_key__startswith="documents:disposed:")
        .exclude(dedupe_key__startswith="documents:disposal:")
    )
    withdrawn = stale.update(dismissed_at=timezone.now(), read_at=timezone.now())
    return {"raised": raised, "withdrawn": withdrawn}
