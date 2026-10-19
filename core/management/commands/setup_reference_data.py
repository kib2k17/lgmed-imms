"""
Load the reference data a real LGMED-IMMS installation starts from - and
nothing else.

    python manage.py setup_reference_data --dry-run   # show what would happen
    python manage.py setup_reference_data             # do it

Creates the Division's sections, the programme categories, the document types
with their retention periods (core/reference_data.py) and the LGUs of Region
XIII (seed_lgus). No demonstration records and no accounts: those are what
`seed_records` and `bootstrap_demo` add for a demo, and neither belongs in a
real installation.

Safe to run again. What is missing is created; what exists is left exactly as
it is - a retention period an administrator has since changed in System
Settings is reported, never overwritten.

The first account is made separately, with Django's own command, so its
password is typed by the person who will hold it:

    python manage.py createsuperuser
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from core.reference_data import CATEGORIES, DOCUMENT_TYPES, SECTIONS


class Command(BaseCommand):
    help = "Load the real reference data (sections, categories, document types, LGUs)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be created or differs, without changing anything.",
        )

    def handle(self, *args, dry_run=False, **options):
        from accounts.models import Section
        from documents.models import DocumentType
        from lgus.models import LGU
        from programs.models import ProgramCategory

        self.dry_run = dry_run
        self.created = 0

        with transaction.atomic():
            self.section("Sections", Section, [
                (name, {"short_name": short}) for name, short in SECTIONS
            ])
            self.section("Programme categories", ProgramCategory, [
                (name, {"description": description}) for name, description in CATEGORIES
            ])
            self.section("Document types", DocumentType, [
                (name, {"code": code, "retention_years": years, "retention_action": action})
                for name, code, years, action in DOCUMENT_TYPES
            ])
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.MIGRATE_HEADING("LGUs"))
        if dry_run:
            self.stdout.write(
                f"  {LGU.objects.count()} in the directory now; seed_lgus would add "
                "whatever of the 78 Region XIII LGUs is missing."
            )
        else:
            call_command("seed_lgus", stdout=self.stdout)

        self.warn_about_demo_data()
        verb = "Would create" if dry_run else "Created"
        self.stdout.write(self.style.SUCCESS(f"\n{verb} {self.created} reference record(s)."))
        self.stdout.write(
            "\nBefore go-live, confirm against the office's records (core/reference_data.py):\n"
            "  - document types and RETENTION PERIODS (placeholders until the records\n"
            "    officer confirms them from the Records Disposition Schedule)\n"
            "  - sections, programme categories, and the LGU roster.\n"
            "Then create the first account:  python manage.py createsuperuser"
        )

    def section(self, title, model, rows):
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        for name, values in rows:
            existing = model.objects.filter(name=name).first()
            if existing is None:
                if not self.dry_run:
                    model.objects.create(name=name, **values)
                self.created += 1
                self.stdout.write(f"  + {name}")
                continue
            differences = [
                f"{field} is {getattr(existing, field)!r} (list says {value!r})"
                for field, value in values.items()
                if getattr(existing, field) != value
            ]
            if differences:
                self.stdout.write(f"  = {name} - kept as it is: " + "; ".join(differences))
            else:
                self.stdout.write(f"  = {name}")

    def warn_about_demo_data(self):
        """A real installation should hold none of the demonstration's records."""
        from accounts.models import User
        from monitoring.models import MonitoringActivity

        from .bootstrap_demo import ACCOUNTS

        demo = list(
            User.objects.filter(username__in=[row[0] for row in ACCOUNTS])
            .values_list("username", flat=True)
        )
        if demo:
            self.stdout.write(self.style.WARNING(
                "\nDemonstration accounts exist (their password is published in the "
                f"README): {', '.join(sorted(demo))}. Deactivate or delete them "
                "before real use."
            ))
        if MonitoringActivity.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Records already exist (for example monitoring activities). If they "
                "are demonstration data, start go-live from a fresh database - see "
                "docs/GO_LIVE.md."
            ))
