"""
The only way to remove audit entries.

    python manage.py prune_audit_log --older-than 1095      # show what would go
    python manage.py prune_audit_log --older-than 1095 --confirm

Deliberately a server-side command rather than a button in the interface: an
audit log that the people it audits can clear from inside the system is not
evidence of anything. Running it requires access to the server, and the run
itself is announced in the log it prunes.

Set the retention period from the office's records-disposition schedule. The
default of 1095 days (three years) is a starting point, not a policy.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from audit.models import Action, AuditEvent
from audit.recording import record

DEFAULT_RETENTION_DAYS = 1095


class Command(BaseCommand):
    help = "Remove audit entries older than the retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=DEFAULT_RETENTION_DAYS,
            help=f"Retention period in days (default {DEFAULT_RETENTION_DAYS}).",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually delete. Without this the command only reports.",
        )

    def handle(self, *args, **options):
        days = options["older_than"]
        if days < 365:
            raise CommandError(
                "Refusing to prune to less than 365 days. If the office's "
                "records-disposition schedule really is shorter than a year, "
                "change it in this command with that schedule cited."
            )

        cutoff = timezone.now() - timezone.timedelta(days=days)
        doomed = AuditEvent.objects.filter(timestamp__lt=cutoff)
        count = doomed.count()
        total = AuditEvent.objects.count()

        self.stdout.write(f"Retention period : {days} days")
        self.stdout.write(f"Cutoff           : {cutoff:%d %B %Y}")
        self.stdout.write(f"Entries held     : {total}")
        self.stdout.write(f"Entries older    : {count}")

        if count == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to remove."))
            return

        if not options["confirm"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry run - nothing was deleted. Re-run with --confirm to "
                    "remove these entries."
                )
            )
            return

        oldest = doomed.order_by("timestamp").first()
        newest = doomed.order_by("-timestamp").first()
        doomed.delete()

        # The pruning is itself recorded, so the gap in the log is explained.
        record(
            Action.DELETE,
            detail=(
                f"Audit retention: {count} entries from "
                f"{oldest.timestamp:%d %b %Y} to {newest.timestamp:%d %b %Y} "
                f"removed under a {days}-day retention period"
            ),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {count} entries. The removal is itself recorded in "
                "the log."
            )
        )
