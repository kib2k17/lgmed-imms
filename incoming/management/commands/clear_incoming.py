"""
Delete every incoming document, with its updates, trail and attachments.

    python manage.py clear_incoming
    python manage.py clear_incoming --no-input     # for scripts; no prompt

Used to empty the register before it is re-synchronised from the office's
spreadsheet. It asks for the word DELETE before it does anything, reports what
it is about to remove, and removes it in one transaction: the table is either
emptied or left as it was.

The rows are deleted through the ORM, not truncated, so the audit log records
each deletion and the standing notifications that pointed at the documents are
withdrawn. Attachment files are removed from disk once the transaction has
committed - a rolled-back delete must not leave records pointing at files that
are gone.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from incoming.models import IncomingDocument, IncomingEvent, IncomingUpdate

CONFIRMATION_WORD = "DELETE"


class Command(BaseCommand):
    help = "Delete all incoming documents, their updates, trail and attachments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-input", "--noinput",
            action="store_false",
            dest="interactive",
            help="Delete without asking for confirmation.",
        )

    def handle(self, *args, interactive=True, **options):
        documents = IncomingDocument.objects.count()
        if not documents:
            self.stdout.write("There are no incoming documents to delete.")
            return

        updates = IncomingUpdate.objects.count()
        events = IncomingEvent.objects.count()
        self.stdout.write(
            self.style.WARNING(
                f"This will permanently delete {documents} incoming document(s), "
                f"{updates} update(s), {events} trail entr{'y' if events == 1 else 'ies'} "
                "and their attached files."
            )
        )

        if interactive:
            answer = input(f"Type {CONFIRMATION_WORD} to continue: ")
            if answer.strip() != CONFIRMATION_WORD:
                raise CommandError("Cancelled. Nothing was deleted.")

        files = self._attachment_files()
        with transaction.atomic():
            self._withdraw_notices()
            deleted, _by_model = IncomingDocument.objects.all().delete()
            transaction.on_commit(lambda: self._remove_files(files))

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {documents} incoming document(s) "
                f"({deleted} rows in all, including updates and trail entries)."
            )
        )

    @staticmethod
    def _attachment_files():
        """(storage, name) of every file attached to a document or an update."""
        files = []
        for model in (IncomingDocument, IncomingUpdate):
            for instance in model.objects.exclude(attachment="").only("attachment"):
                files.append((instance.attachment.storage, instance.attachment.name))
        return files

    def _remove_files(self, files):
        removed = 0
        for storage, name in files:
            try:
                if storage.exists(name):
                    storage.delete(name)
                    removed += 1
            except OSError as error:
                self.stderr.write(f"Could not remove {name}: {error}")
        if removed:
            self.stdout.write(f"Removed {removed} attached file(s).")

    @staticmethod
    def _withdraw_notices():
        """Notices about documents that will no longer exist - they would 404."""
        from django.db.models import Q
        from django.urls import reverse

        from notifications.models import Notification

        Notification.objects.filter(
            Q(dedupe_key__startswith="incoming:")
            | Q(url__startswith=reverse("incoming:list"))
        ).delete()
