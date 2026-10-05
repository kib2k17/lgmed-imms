"""
Keeps the Documents register in step with Incoming and Outgoing Monitoring.

Every document the Division receives belongs in the register, so each incoming
document has one register entry (`documents.Document.incoming`), created when
the document is recorded and moved on by every step after it:

  Incoming / Outgoing                     Documents register
  recorded, or imported                   For review / Received
  reviewed by the Division Chief          For assignment
  assigned (LGMED code issued)            Assigned - reference becomes the code
  acknowledged, moved to Outgoing         In progress
  updates, returned for revision          In progress
  completed                               Completed - retention clock starts
  communication sent                      noted on the trail

Every file uploaded along the way is captured too: the incoming attachment is
the entry's file (a replacement becomes a new version), and each focal
person's supporting attachment and the file of the communication sent are
held with it as supporting files (`documents.SupportingFile`). A row of the
outgoing register that answers no incoming document gets an entry of its own
(`sync_outgoing`).

The sync runs one way. Incoming and Outgoing are where the work is done; the
entry follows them and refuses to be moved on its own (see
`documents.workflow._refuse_if_synced`). What the register adds - archiving,
retention and disposal - happens only there, and once an entry is archived the
sync leaves its status alone.

It writes the register's trail but raises no notifications: the incoming
workflow has already told the people concerned.
"""

import os

from django.db import transaction
from django.utils import timezone

from .models import IncomingStatus

# Where each incoming status sits in the register's lifecycle.
_STATUS = {
    IncomingStatus.FOR_REVIEW: "FOR_REVIEW",
    IncomingStatus.IMPORTED: "RECEIVED",
    IncomingStatus.ASSIGNED: "ASSIGNED",
    IncomingStatus.ACKNOWLEDGED: "IN_PROGRESS",
    IncomingStatus.IN_PROGRESS: "IN_PROGRESS",
    IncomingStatus.FOR_ACTION: "IN_PROGRESS",
    IncomingStatus.PENDING: "IN_PROGRESS",
    IncomingStatus.RETURNED: "IN_PROGRESS",
    IncomingStatus.COMPLETED: "COMPLETED",
}


def register_status(document):
    status = _STATUS.get(document.status, "RECEIVED")
    # Read by the Chief but not yet given to anyone: the register calls that
    # "for assignment".
    if status == "FOR_REVIEW" and document.reviewed_at is not None:
        return "FOR_ASSIGNMENT"
    return status


def _owner(document, actor):
    """The register needs an owner; whoever recorded the document is it."""
    from accounts.models import User

    for candidate in (document.created_by, actor, getattr(document, "assigned_to", None)):
        if candidate is not None and getattr(candidate, "pk", None):
            return candidate
    return User.objects.filter(is_superuser=True).order_by("pk").first()


def _reference(entry, document):
    """The LGMED code once issued, the DMS number until then - never a clash."""
    from documents.models import Document

    wanted = (document.lgmed_code or document.docket_number)[:60]
    taken = Document.objects.filter(reference_number=wanted).exclude(pk=entry.pk)
    if taken.exists():
        wanted = f"DMS-{document.docket_number}"[:60]
    return wanted


@transaction.atomic
def sync(document, actor=None, *, event_type=None, detail="", notes=""):
    """
    Bring the document's register entry up to date, creating it if need be.

    `event_type` (a `documents.models.EventType`) and `detail` describe what
    happened, for the register's trail; without them the entry is updated
    silently, as a backfill does.
    """
    from documents.models import Document, DocumentStatus, RetentionAction
    from documents.models import RetentionDisposition
    from documents.workflow import log

    entry = Document.objects.filter(incoming=document).first()
    created = entry is None
    if created:
        owner = _owner(document, actor)
        if owner is None:
            return None
        entry = Document(incoming=document, owner=owner,
                         created_by=document.created_by or owner)

    # -- the document's details, always as Incoming holds them --------------
    entry.title = document.subject[:255]
    entry.subject = document.subject[:255]
    entry.document_type_id = document.document_type_id
    entry.sender = document.source_office[:200]
    entry.date_received = document.date_received
    entry.year = document.date_received.year
    entry.remarks = document.initial_remarks
    entry.description = "\n".join(
        line for line in (
            f"LGMED code: {document.lgmed_code}" if document.lgmed_code else "",
            f"DMS / docket number: {document.docket_number}",
        ) if line
    )
    entry.reference_number = _reference(entry, document)

    entry.reviewed_by_id = document.reviewed_by_id
    entry.reviewed_at = document.reviewed_at
    entry.review_notes = document.review_notes
    entry.assigned_to_id = document.assigned_to_id
    entry.assigned_by_id = document.assigned_by_id
    entry.assigned_at = document.assigned_at
    entry.assignment_remarks = document.assignment_remarks
    entry.due_date = document.due_date
    if actor is not None and getattr(actor, "is_authenticated", False):
        entry.updated_by = actor

    # -- where it stands, unless the records officer has filed it away ------
    from_status = entry.status
    if not entry.is_archived and not entry.is_disposed:
        to_status = register_status(document)
        if to_status == DocumentStatus.COMPLETED and not entry.is_completed:
            finished = document.completed_at or timezone.now()
            entry.completed_at = finished
            entry.approved_at = finished
            if actor is not None and getattr(actor, "is_authenticated", False):
                entry.approved_by = actor
            if entry.retention_until is None:
                entry.retention_until = entry.computed_retention_until(
                    timezone.localtime(finished).date()
                )
            if entry.document_type.retention_action == RetentionAction.PERMANENT:
                entry.retention_disposition = RetentionDisposition.PERMANENT
        elif to_status != DocumentStatus.COMPLETED and entry.is_completed:
            # Reopened - returned for revision after it was closed.
            entry.completed_at = None
            entry.approved_at = None
            entry.approved_by = None
            if entry.retention_disposition == RetentionDisposition.ACTIVE:
                entry.retention_until = None
        entry.status = to_status

    # -- the file travels with it --------------------------------------------
    file_changed = bool(document.attachment) and entry.file.name != document.attachment.name
    if file_changed:
        entry.file.name = document.attachment.name

    entry.save()

    if created:
        log(
            entry, actor, event_type or "REGISTERED",
            detail=(
                f"Registered from Incoming Monitoring as {entry.reference_number}"
                + (f", received from {entry.sender}" if entry.sender else "")
            ),
            notes=entry.remarks,
            to_status=entry.status,
        )
    elif event_type:
        log(entry, actor, event_type, detail=detail, notes=notes,
            from_status=from_status if from_status != entry.status else "",
            to_status=entry.status)

    if file_changed:
        first = not entry.versions.exists()
        entry.adopt_current_file(
            user=actor,
            reason="Initial upload" if first else "Attachment replaced in Incoming Monitoring",
        )
        log(entry, actor, "UPLOADED" if first else "VERSION_UPLOADED",
            detail=f"File from Incoming Monitoring ({entry.file_name})")

    _capture_supporting_files(entry, document, actor)
    return entry


def _capture_supporting_files(entry, document, actor):
    """Hold every file uploaded in the work on the document with its entry."""
    from documents.models import FileSource, SupportingFile
    from documents.workflow import log

    captured = set(
        entry.supporting_files.exclude(file="").values_list("file", flat=True)
    )

    for update in document.updates.exclude(attachment="").select_related("created_by"):
        if update.attachment.name in captured:
            continue
        SupportingFile.objects.create(
            document=entry,
            source=FileSource.UPDATE,
            title=f"Supporting attachment - {update.get_status_display()}",
            file=update.attachment.name,
            incoming_update=update,
            uploaded_by=update.created_by,
            uploaded_at=update.created_at,
        )
        captured.add(update.attachment.name)
        log(
            entry, actor or update.created_by, "UPLOADED",
            detail=(
                "Supporting file from an update captured "
                f"({os.path.basename(update.attachment.name)})"
            ),
            notes=update.action_taken,
        )

    outgoing = document.outgoing_document
    if outgoing is not None and outgoing.file and outgoing.file.name not in captured:
        SupportingFile.objects.create(
            document=entry,
            source=FileSource.OUTGOING,
            title=f"Communication sent - {outgoing.communication_type or 'reply'}",
            file=outgoing.file.name,
            outgoing=outgoing,
            uploaded_by=outgoing.updated_by or actor,
        )
        log(entry, actor, "UPLOADED",
            detail=f"File of the communication sent captured ({outgoing.file_name})")


def _outgoing_type(outgoing):
    """The register's type for an outgoing row: its own if one matches."""
    from documents.models import DocumentType

    if outgoing.communication_type:
        match = DocumentType.objects.filter(
            name__iexact=outgoing.communication_type.strip()
        ).first()
        if match is not None:
            return match
    document_type, _created = DocumentType.objects.get_or_create(
        name="Outgoing Communication",
        defaults={
            "description": (
                "Communications sent by the Division, from Outgoing Monitoring. "
                "Reclassify as needed."
            ),
        },
    )
    return document_type


@transaction.atomic
def sync_outgoing(outgoing, actor=None):
    """
    Bring an outgoing communication into the register.

    One that answers an incoming document is part of that document's entry -
    its file is captured there - so only a row that stands alone, as the
    spreadsheet register's history mostly does, gets an entry of its own.
    """
    from documents.models import Document, DocumentStatus, RetentionAction
    from documents.models import RetentionDisposition
    from documents.workflow import log

    if outgoing.incoming_id:
        return sync(outgoing.incoming, actor)

    entry = Document.objects.filter(outgoing=outgoing).first()
    created = entry is None
    if created:
        owner = _owner(outgoing, actor)
        if owner is None:
            return None
        entry = Document(outgoing=outgoing, owner=owner,
                         created_by=outgoing.created_by or owner)

    code = outgoing.control_code
    entry.title = (outgoing.subject or code)[:255]
    entry.subject = (outgoing.subject or "")[:255]
    entry.document_type = _outgoing_type(outgoing)
    entry.sender = ""
    entry.date_created = outgoing.date_sent
    entry.year = (outgoing.date_sent or timezone.localdate()).year
    entry.remarks = outgoing.remarks
    entry.description = "\n".join(
        line for line in (
            f"LGMED code: {code}",
            f"Sent to: {outgoing.sent_to}" if outgoing.sent_to else "",
            f"Sent via: {outgoing.sent_via}" if outgoing.sent_via else "",
            f"DMS number (incoming): {outgoing.incoming_reference}"
            if outgoing.incoming_reference else "",
            f"DMS number (outgoing): {outgoing.dms_number}" if outgoing.dms_number else "",
        ) if line
    )
    wanted = code[:60]
    if Document.objects.filter(reference_number=wanted).exclude(pk=entry.pk).exists():
        wanted = f"OUT-{outgoing.pk}"
    entry.reference_number = wanted

    from_status = entry.status
    if not entry.is_archived and not entry.is_disposed:
        if outgoing.is_sent:
            if not entry.is_completed:
                entry.completed_at = entry.approved_at = timezone.now()
                if entry.retention_until is None:
                    entry.retention_until = entry.computed_retention_until(
                        outgoing.date_sent
                    )
                if entry.document_type.retention_action == RetentionAction.PERMANENT:
                    entry.retention_disposition = RetentionDisposition.PERMANENT
            entry.status = DocumentStatus.COMPLETED
        else:
            entry.status = DocumentStatus.IN_PROGRESS

    file_changed = bool(outgoing.file) and entry.file.name != outgoing.file.name
    if file_changed:
        entry.file.name = outgoing.file.name
    entry.save()

    if created:
        log(entry, actor, "REGISTERED",
            detail=f"Registered from Outgoing Monitoring as {entry.reference_number}",
            notes=entry.remarks, to_status=entry.status)
    elif from_status != entry.status or actor is not None:
        log(entry, actor, "EDITED", detail="Updated from Outgoing Monitoring",
            from_status=from_status if from_status != entry.status else "",
            to_status=entry.status)
    if file_changed:
        first = not entry.versions.exists()
        entry.adopt_current_file(
            user=actor,
            reason="Initial upload" if first else "File replaced in Outgoing Monitoring",
        )
        log(entry, actor, "UPLOADED" if first else "VERSION_UPLOADED",
            detail=f"File from Outgoing Monitoring ({entry.file_name})")
    return entry


def sync_all_outgoing(queryset=None):
    """Create or refresh the register entry of every stand-alone outgoing row."""
    from outgoing.models import OutgoingDocument

    queryset = queryset if queryset is not None else OutgoingDocument.objects.all()
    count = 0
    for outgoing in queryset.filter(incoming__isnull=True).select_related(
        "created_by"
    ).iterator():
        if sync_outgoing(outgoing) is not None:
            count += 1
    return count


def sync_all(queryset=None):
    """Create or refresh the register entry of every incoming document."""
    from .models import IncomingDocument

    queryset = queryset if queryset is not None else IncomingDocument.objects.all()
    count = 0
    for document in queryset.select_related(
        "created_by", "assigned_to", "document_type"
    ).iterator():
        if sync(document) is not None:
            count += 1
    return count
