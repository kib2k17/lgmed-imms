"""
Bring every incoming document and outgoing communication into the Documents
register, with every file uploaded for them, or bring them up to date there.

New activity keeps the register in step by itself (see incoming/register.py).
This is for what came before: records made or imported before the sync
existed. Safe to run more than once - an entry or a captured file is created
only where none exists, and otherwise refreshed.
"""

from django.core.management.base import BaseCommand

from incoming.register import sync_all, sync_all_outgoing


class Command(BaseCommand):
    help = (
        "Create or refresh the Documents register entry of every incoming "
        "document and stand-alone outgoing communication, with their files."
    )

    def handle(self, *args, **options):
        incoming = sync_all()
        outgoing = sync_all_outgoing()
        self.stdout.write(self.style.SUCCESS(
            f"{incoming} incoming document(s) and {outgoing} stand-alone outgoing "
            "communication(s) are in the register."
        ))
