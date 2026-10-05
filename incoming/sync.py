"""
How the Incoming register's rows become incoming documents.

Used by `datasync`; see `datasync/profiles.py` for which spreadsheet columns
are read. A synced document arrives at "Imported from spreadsheet" - outside
the workflow until the Chief assigns it - and its trail says where it came
from, down to the sheet and row.
"""

from datasync.targets import SyncTarget, chunked
from documents.models import DocumentType

from .models import EventType, IncomingDocument, IncomingEvent, IncomingStatus

# The register does not say what kind of document each entry is. Synced
# documents are filed under this type until someone reclassifies them.
DEFAULT_TYPE_NAME = "Unclassified"

# The model requires a subject; a register row with a docket and nothing else
# is still a document that arrived.
MISSING_SUBJECT = "(No subject in the register)"


def default_document_type():
    document_type, _created = DocumentType.objects.get_or_create(
        name=DEFAULT_TYPE_NAME,
        defaults={
            "description": (
                "Incoming documents synchronised from the spreadsheet register, "
                "which does not record a document type. Reclassify as needed."
            ),
        },
    )
    return document_type


class IncomingTarget(SyncTarget):
    model = IncomingDocument
    key_field = "docket_number"
    key_label = "Docket Number"
    key_max_length = IncomingDocument._meta.get_field("docket_number").max_length
    list_url_name = "incoming:list"
    field_labels = {
        "date_received": "Date received",
        "source_office": "HUC/Province",
        "subject": "Subject",
        "initial_remarks": "Assigned Focal/Remarks",
    }

    def fields_for(self, row):
        values = row.values
        subject_max = IncomingDocument._meta.get_field("subject").max_length
        source_max = IncomingDocument._meta.get_field("source_office").max_length
        return {
            "date_received": row.date,
            "source_office": values.get("source", "")[:source_max],
            "subject": values.get("subject", "")[:subject_max],
            "initial_remarks": values.get("remarks", ""),
        }

    def create(self, planned, user, batch):
        if not planned:
            return 0
        document_type = default_document_type()
        documents = []
        for change in planned:
            fields = dict(change.fields)
            fields["subject"] = fields["subject"] or MISSING_SUBJECT
            documents.append(
                self.stamp(
                    IncomingDocument(
                        docket_number=change.row.key,
                        document_type=document_type,
                        status=IncomingStatus.IMPORTED,
                        **fields,
                    ),
                    user,
                )
            )
        IncomingDocument.objects.bulk_create(documents, batch_size=500)

        # MySQL does not hand back the new primary keys from a bulk insert, so
        # the trail entries look them up by docket number.
        where = {change.row.key.upper(): change.row.location for change in planned}
        events = []
        for chunk in chunked(where):
            for pk, docket in IncomingDocument.objects.filter(
                docket_number__in=chunk
            ).values_list("pk", "docket_number"):
                events.append(
                    self._event(
                        pk, user, EventType.RECORDED,
                        detail="Imported from the spreadsheet register",
                        notes=f"{batch.original_name} - {where[docket.upper()]}",
                    )
                )
        IncomingEvent.objects.bulk_create(events, batch_size=500)

        # Every document received belongs in the Documents register too.
        from .register import sync_all

        for chunk in chunked(where):
            sync_all(IncomingDocument.objects.filter(docket_number__in=chunk))
        return len(documents)

    def after_update(self, change, user, batch):
        event = self._event(
            change.instance.pk, user, EventType.EDITED,
            detail="Updated from the spreadsheet register: "
            + ", ".join(self.labels(change.changes)),
            notes=f"{batch.original_name} - {change.row.location}",
        )
        event.save()

        from .register import sync

        sync(change.instance, user, event_type="EDITED",
             detail="Updated from the spreadsheet register")

    @staticmethod
    def _event(document_id, user, event_type, *, detail, notes):
        return IncomingEvent(
            document_id=document_id,
            actor=user,
            actor_label=user.get_display_name(),
            actor_role=user.get_role_display(),
            event_type=event_type,
            detail=detail[:255],
            notes=notes,
            to_status=IncomingStatus.IMPORTED if event_type == EventType.RECORDED else "",
        )
