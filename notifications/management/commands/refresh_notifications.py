"""
Find work that is waiting and tell the people who can act on it.

    python manage.py refresh_notifications

Some things that need attention are not events. Nothing *happens* on the day a
follow-up becomes overdue - it simply is overdue, and stays overdue until
someone acts. Conditions like that cannot be caught by a signal, so this
command looks for them.

Run it on a schedule, once each working morning:

    Windows Task Scheduler:
        venv\\Scripts\\python.exe manage.py refresh_notifications
    cron:
        0 7 * * 1-5  /path/to/venv/bin/python manage.py refresh_notifications

Safe to run repeatedly. Existing conditions are deduplicated, so a follow-up
overdue for three weeks produces one notification rather than twenty-one, and
conditions that have since been resolved are withdrawn.
"""

from django.core.management.base import BaseCommand

from notifications.service import refresh_standing_notices


class Command(BaseCommand):
    help = "Raise notifications for overdue and pending work; withdraw resolved ones."

    def handle(self, *args, **options):
        summary = refresh_standing_notices()

        self.stdout.write(f"Notifications raised    : {summary['raised']}")
        self.stdout.write(f"Notifications withdrawn : {summary['withdrawn']}")

        if summary["raised"] or summary["withdrawn"]:
            self.stdout.write(self.style.SUCCESS("Notifications are up to date."))
        else:
            self.stdout.write(
                self.style.SUCCESS("Nothing to raise or withdraw - all clear.")
            )
