"""
Create one account per role so the role-based interface can be demonstrated.

    python manage.py bootstrap_demo

Development and demonstration only. Passwords are printed to the console and
must never be used on a deployed system.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role, User

ACCOUNTS = [
    ("lgmed.superadmin", "Maria Clara", "Reyes", Role.SUPERADMIN,
     "Information Technology Officer III"),
    ("lgmed.admin", "Antonio", "Villanueva", Role.ADMIN,
     "Division Chief"),
    ("lgmed.staff", "Karl Kevin", "Bacon", Role.LGMED_STAFF,
     "Information Systems Analyst"),
    ("lgmed.encoder", "Rosario", "Mendoza", Role.ENCODER,
     "Administrative Assistant III"),
    ("lgmed.viewer", "Jose", "Santos", Role.VIEWER,
     "Local Government Operations Officer II"),
]

PASSWORD = "LgmedDemo!2026"


class Command(BaseCommand):
    help = "Create demonstration accounts, one for each LGMED-iMMS role."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=PASSWORD,
            help="Password to set on every demonstration account.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError(
                "bootstrap_demo refuses to run with DEBUG=False. "
                "Create real accounts with `createsuperuser` instead."
            )

        password = options["password"]
        created, updated = 0, 0

        for username, first, last, role, position in ACCOUNTS:
            user, is_new = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": role,
                    "position": position,
                    "email": f"{username}@caraga.dilg.gov.ph",
                },
            )
            user.first_name = first
            user.last_name = last
            user.role = role
            user.position = position
            user.is_staff = role in (Role.SUPERADMIN, Role.ADMIN)
            user.is_superuser = role == Role.SUPERADMIN
            user.set_password(password)
            user.save()

            created += is_new
            updated += not is_new
            self.stdout.write(
                f"  {username:22} {user.get_role_display():25} {position}"
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{created} account(s) created, {updated} updated. "
                f"Password for all: {password}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "Demonstration accounts only - remove them before deployment."
            )
        )
