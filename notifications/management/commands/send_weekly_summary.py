"""
Email the Division Chief a summary of the week's outstanding work.

    python manage.py send_weekly_summary            # once per ISO week
    python manage.py send_weekly_summary --force    # again, now (testing)

Meant to run every morning from the same scheduler as the submission
reminders (deploy/systemd, deploy/windows). Each recipient receives one
summary per week - the first run of the week sends it, later runs that week
do nothing - and a failed send is simply tried again on the next run.

The marker that it was sent is an ordinary notification ("Weekly summary
sent", deduplicated per week), so the summary is also on the bell for anyone
who missed the email.

Recipients: every active account that may review incoming documents (the
Division Chief and Administrators), with an email address.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


def week_key(today):
    year, week, _ = today.isocalendar()
    return f"weekly-summary:{year}-W{week:02d}"


def build_summary(today):
    """What the email says: the figures, the overdue documents, the missing papers."""
    from core import stats
    from incoming.models import IncomingDocument

    overdue = list(
        IncomingDocument.objects.overdue(today)
        .select_related("assigned_to")
        .order_by("due_date")[:10]
    )

    missing, schedule = [], None
    try:
        from submissions.services import default_schedule_for_staff, pending_for

        schedule = default_schedule_for_staff()
        if schedule is not None and schedule.deadline > timezone.now():
            missing = sorted(row.staff.get_display_name() for row in pending_for(schedule))
        else:
            schedule = None
    except Exception:  # the summary still goes out without this section
        logger.exception("Monthly submission figures unavailable for the weekly summary")

    return {
        "today": today,
        "pending": stats.pending_actions(),
        "overdue": overdue,
        "schedule": schedule,
        "missing": missing,
    }


def absolute(path):
    base = settings.LGMED_SITE_URL or ("http://localhost:8000" if settings.DEBUG else "")
    return f"{base}{path}"


class Command(BaseCommand):
    help = "Email the weekly summary of outstanding work to the Division Chief."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Send even if this week's summary already went out.")

    def handle(self, *args, force=False, **options):
        from accounts.capabilities import users_with
        from notifications.models import Category, Level, Notification
        from notifications.service import notify

        today = timezone.localdate()
        key = week_key(today)
        recipients = [u for u in users_with("can_review_incoming") if u.email]
        due = [
            user for user in recipients
            if force or not Notification.objects.filter(recipient=user, dedupe_key=key).exists()
        ]
        if not due:
            self.stdout.write("Nothing to send: this week's summary has gone out.")
            return

        summary = build_summary(today)
        context = {
            **summary,
            "dashboard_url": absolute(reverse("core:dashboard")),
            "incoming_url": absolute(f"{reverse('incoming:list')}?view=overdue"),
            "submissions_url": absolute(reverse("submissions:home")),
        }
        sent = 0
        for user in due:
            message = EmailMultiAlternatives(
                subject=f"LGMED-IMMS weekly summary - {today:%d %B %Y}",
                body=render_to_string("emails/weekly_summary.txt", {**context, "user": user}),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            message.attach_alternative(
                render_to_string("emails/weekly_summary.html", {**context, "user": user}),
                "text/html",
            )
            try:
                message.send()
            except Exception:
                logger.exception("Weekly summary to %s could not be sent", user.email)
                continue
            # The marker that this week's summary reached them. A forced resend
            # replaces the week's marker rather than being deduplicated away.
            if force:
                Notification.objects.filter(recipient=user, dedupe_key=key).delete()
            notify(
                [user], title="Weekly summary sent to your email",
                message=f"{sum(item['count'] for item in summary['pending'])} items need attention; "
                        f"{len(summary['overdue'])} incoming documents overdue.",
                url=reverse("core:dashboard"), category=Category.SYSTEM,
                level=Level.INFO, dedupe_key=key,
            )
            sent += 1
        self.stdout.write(f"Weekly summary sent to {sent} of {len(due)} recipient(s).")
