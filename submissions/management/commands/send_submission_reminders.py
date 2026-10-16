"""
Send the Monthly Submissions emails that are due.

    python manage.py send_submission_reminders

Does three things, in order:

  1. queues the upcoming-deadline reminders that are due (by default 7, 3 and
     1 days before the Chief's deadline, and on the day itself), for staff
     who have not yet submitted both the MMIA and the DTR;
  2. queues overdue notices for deadlines that have passed with something
     still missing;
  3. sends everything queued - including announcements and confirmations
     that could not be sent at the time, and failures due a retry.

Run it on a schedule. Hourly is right: every notice has a unique key, so a
run that finds nothing new sends nothing, and two runs that overlap cannot
send the same email twice. Reminders wait until
MONTHLY_SUBMISSION_REMINDER_HOUR (08:00 Asia/Manila by default).

    Windows Task Scheduler (see deploy/windows/register-submission-reminders.ps1):
        venv\\Scripts\\python.exe manage.py send_submission_reminders
    systemd (see deploy/systemd/lgmed-submission-reminders.timer), or cron:
        0 * * * *  /srv/lgmed-imms/venv/bin/python manage.py send_submission_reminders
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from submissions import notify
from submissions.models import EmailStatus, MonthlySubmissionNotification


class Command(BaseCommand):
    help = "Queue and send MMIA/DTR deadline reminders, overdue notices and retries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-send", action="store_true",
            help="Queue what is due but do not send anything.",
        )
        parser.add_argument(
            "--at", help=(
                "Pretend it is this moment (ISO 8601, e.g. 2026-10-25T09:00+08:00). "
                "For testing a schedule; never needed in production."
            ),
        )

    def handle(self, *args, **options):
        at = timezone.now()
        if options.get("at"):
            parsed = parse_datetime(options["at"])
            if parsed is None:
                self.stderr.write(self.style.ERROR("--at is not an ISO 8601 date and time."))
                return
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            at = parsed

        queued = notify.queue_scheduled(at)
        self.stdout.write(f"Reminders queued      : {queued['reminders']}")
        self.stdout.write(f"Overdue notices queued: {queued['overdue']}")

        if options["no_send"]:
            self.stdout.write("Sending skipped (--no-send).")
            return

        sent = notify.dispatch(at=at)
        self.stdout.write(f"Emails sent           : {sent['sent']}")
        self.stdout.write(f"Emails failed         : {sent['failed']}")
        self.stdout.write(f"Emails skipped        : {sent['skipped']}")

        waiting = MonthlySubmissionNotification.objects.filter(
            email_status__in=(EmailStatus.PENDING, EmailStatus.FAILED)
        ).count()
        if sent["failed"]:
            self.stdout.write(self.style.WARNING(
                f"{sent['failed']} email(s) failed and will be retried on a later run. "
                f"{waiting} waiting in total."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Monthly submission emails are up to date."))
