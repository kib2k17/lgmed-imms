"""
Carry the documents that were already in the repository into the new register.

The old module held a small repository: a title, a type, a year, a file and a
status of draft / for review / published / archived. The Document Management
module asks more of every record - it must have an owner, a control number and,
once completed, a retention period - so those are worked out here rather than
left blank for someone to discover later.

Four things are settled:

  * `PUBLISHED` no longer exists as a status. A published document had been
    approved and released, which in the new lifecycle is `COMPLETED`; its
    `is_public` flag is what actually kept it on the website, and that is
    untouched, so nothing disappears from the public library.
  * Every document is given an owner. Where the old row recorded who encoded
    it, that is the owner. Where it did not - and none of the seeded rows did -
    it falls to an administrator, so the record is answerable to someone real
    rather than to nobody.
  * Every document is given a control number, issued in the order the records
    were created so the sequence is stable.
  * A document that already had a file gets version 1, pointed at that same
    stored file. Backfilling the history is the only way the version list can
    honestly say a file existed before this migration ran.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    DocumentVersion = apps.get_model("documents", "DocumentVersion")
    DocumentEvent = apps.get_model("documents", "DocumentEvent")
    User = apps.get_model("accounts", "User")

    fallback = (
        User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
        or User.objects.filter(role="ADMIN", is_active=True).order_by("pk").first()
        or User.objects.order_by("pk").first()
    )

    # Issued in creation order, so the numbers run with the register rather
    # than with whatever order the database happens to return.
    sequences = {}

    for document in Document.objects.order_by("created_at", "pk"):
        changed = []

        if document.status == "PUBLISHED":
            document.status = "COMPLETED"
            changed.append("status")

        if document.owner_id is None:
            document.owner_id = document.created_by_id or (
                fallback.pk if fallback else None
            )
            changed.append("owner")

        if not document.reference_number:
            year = document.year
            sequences[year] = sequences.get(year, 0) + 1
            document.reference_number = f"LGMED-{year}-{sequences[year]:04d}"
            changed.append("reference_number")

        if not document.subject:
            document.subject = document.title[:255]
            changed.append("subject")

        if document.date_created is None:
            document.date_created = document.created_at.date()
            changed.append("date_created")

        # A document that was already finished starts its retention period
        # from the day it was completed, which is the best evidence available:
        # the day the old record was last touched.
        if document.status == "COMPLETED" and document.completed_at is None:
            document.completed_at = document.updated_at
            changed.append("completed_at")

        if changed:
            document.save()

        if document.file and not DocumentVersion.objects.filter(
            document=document
        ).exists():
            DocumentVersion.objects.create(
                document=document,
                version_number=1,
                file=document.file,
                uploaded_by=document.created_by_id and document.created_by,
                reason="Carried over from the document repository.",
            )

        if not DocumentEvent.objects.filter(document=document).exists():
            DocumentEvent.objects.create(
                document=document,
                actor=None,
                actor_label="System",
                actor_role="",
                event_type="REGISTERED",
                detail=(
                    f"Carried over from the document repository as "
                    f"{document.reference_number}"
                ),
                to_status=document.status,
            )


def unbackfill(apps, schema_editor):
    """
    Put the statuses back, and nothing else.

    Control numbers, owners and version rows are new information; discarding
    them on a reverse would lose work rather than undo it, and a migration
    that quietly destroys records is worse than one that will not reverse.
    """
    Document = apps.get_model("documents", "Document")
    Document.objects.filter(status="COMPLETED").update(status="PUBLISHED")


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_document_management"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
