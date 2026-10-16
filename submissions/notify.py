"""
Telling staff about the deadline: the notification bell and email.

The bell is the system's own (notifications.service.notify) - this module
adds no second notification store. Email goes through Django's mail
framework and the SMTP server configured in <venv>/lgmed.env.

Every email is first written to MonthlySubmissionNotification under a unique
key, then claimed and sent:

    queue     the key makes a second copy impossible, even when two
              scheduled runs overlap - the database refuses the duplicate.
    claim     an atomic conditional UPDATE moves the row to SENDING; only
              one worker can win it.
    send      success -> SENT; any SMTP failure -> FAILED, retried by the
              next scheduled run up to MONTHLY_SUBMISSION_EMAIL_MAX_ATTEMPTS.

The email's content is worked out when it is sent, not when it is queued, so
a reminder that is retried after the staff member has completed is dropped
(SKIPPED) rather than sent late and wrong.
"""

import logging
import threading
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import IntegrityError, connections, transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core.context_processors import AGENCY
from notifications.models import Category, Level, Notification
from notifications.service import notify as notify_bell

from .models import (
    DOCUMENT_TITLES,
    MANILA,
    DocumentKind,
    EmailStatus,
    MonthlyStaffSubmission,
    MonthlySubmissionNotification,
    MonthlySubmissionSchedule,
    NotificationType,
)

logger = logging.getLogger(__name__)

SYSTEM_NAME = "LGMED-iMMS"
STALE_SENDING = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _deadline_text(value):
    local = value.astimezone(MANILA)
    hour = local.strftime("%I:%M %p").lstrip("0")
    return f"{local:%B} {local.day}, {local.year}, at {hour}"


def _date_text(value):
    local = value.astimezone(MANILA)
    return f"{local:%B} {local.day}, {local.year}"


def _site_url(base_url=""):
    if base_url:
        return base_url.rstrip("/")
    if settings.LGMED_SITE_URL:
        return settings.LGMED_SITE_URL
    return "http://localhost:8000" if settings.DEBUG else ""


def module_url(schedule=None):
    path = reverse("submissions:home")
    return f"{path}?period={schedule.pk}" if schedule is not None else path


def _bell_key(schedule, user, suffix):
    return f"monthly:{schedule.pk}:{user.pk}:{suffix}"[:120]


def _bell(user, schedule, suffix, *, title, message, level=Level.ACTION,
          category=Category.ASSIGNMENT):
    return notify_bell(
        [user], title=title, message=message, url=module_url(schedule),
        category=category, level=level,
        dedupe_key=_bell_key(schedule, user, suffix),
    )


def _withdraw(schedule, user=None, keep_completed=True):
    """Dismiss bell notices for a schedule that no longer hold."""
    prefix = f"monthly:{schedule.pk}:" + (f"{user.pk}:" if user is not None else "")
    notices = Notification.objects.filter(
        dedupe_key__startswith=prefix, dismissed_at__isnull=True
    )
    if keep_completed:
        notices = notices.exclude(dedupe_key__endswith=":completed")
    now = timezone.now()
    return notices.update(dismissed_at=now, read_at=now)


def _submitters():
    from .services import submitters

    return submitters()


def _is_complete(user, schedule):
    return MonthlyStaffSubmission.objects.filter(
        staff=user, schedule=schedule, completed_at__isnull=False
    ).exists()


def queue_email(recipient, schedule, notification_type, key, params=None):
    """Write one email to the outbox, or return None if it is already there."""
    try:
        with transaction.atomic():
            return MonthlySubmissionNotification.objects.create(
                recipient=recipient,
                schedule=schedule,
                notification_type=notification_type,
                dedupe_key=key[:191],
                params=params or {},
                email_address=recipient.email or "",
            )
    except IntegrityError:
        return None


def kick(ids):
    """
    Send freshly queued emails now rather than at the next scheduled run.

    In a background thread, so a Chief setting a deadline for forty staff is
    not kept waiting on forty SMTP conversations. If the process stops first,
    the rows are still PENDING and the scheduled command sends them.
    """
    ids = [pk for pk in ids if pk]
    if not ids or not settings.MONTHLY_SUBMISSION_SEND_IMMEDIATELY:
        return

    def run():
        try:
            dispatch(ids=ids)
        except Exception:  # pragma: no cover
            logger.exception("Monthly submission emails could not be dispatched")
        finally:
            connections.close_all()

    threading.Thread(target=run, name="monthly-submission-mail", daemon=True).start()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def announce(schedule, base_url=""):
    """The Chief set a new reporting month's deadline: tell every staff member."""
    queued = []
    for person in _submitters():
        _bell(
            person, schedule, f"deadline:{schedule.deadline_stamp}",
            title=f"MMIA and DTR deadline set for {schedule.period_label}",
            message=(
                f"Your MMIA and DTR submission deadline for {schedule.period_label} "
                f"is {_deadline_text(schedule.deadline)}."
            ),
        )
        row = queue_email(
            person, schedule, NotificationType.ANNOUNCEMENT,
            f"announce:{schedule.pk}:{schedule.deadline_stamp}:{person.pk}",
            {"stamp": schedule.deadline_stamp, "base_url": base_url},
        )
        if row:
            queued.append(row.pk)
    kick(queued)
    return len(queued)


def deadline_changed(schedule, old_deadline, extended, base_url=""):
    """
    The Chief moved a deadline. Notices about the old one are withdrawn and
    everyone who has not completed is told the new one.
    """
    _withdraw(schedule)
    word = "extended" if extended else "changed"
    queued = []
    for person in _submitters():
        if _is_complete(person, schedule):
            continue
        _bell(
            person, schedule, f"deadline:{schedule.deadline_stamp}",
            title=f"MMIA and DTR deadline {word}: {schedule.period_label}",
            message=(
                f"The {schedule.period_label} deadline is now "
                f"{_deadline_text(schedule.deadline)}."
            ),
        )
        row = queue_email(
            person, schedule, NotificationType.DEADLINE_CHANGED,
            f"changed:{schedule.pk}:{schedule.deadline_stamp}:{person.pk}",
            {
                "stamp": schedule.deadline_stamp,
                "old_deadline": old_deadline.isoformat(),
                "extended": extended,
                "base_url": base_url,
            },
        )
        if row:
            queued.append(row.pk)
    kick(queued)
    return len(queued)


def submission_progress(submission, became_complete, base_url=""):
    """After an upload: a confirmation when both are in, a nudge when one is."""
    staff = submission.staff
    schedule = submission.schedule
    if became_complete:
        _withdraw(schedule, staff)
        _bell(
            staff, schedule, "completed",
            title=f"{schedule.period_label} submission completed",
            message=(
                f"Your MMIA and DTR submission for {schedule.period_label} "
                "has been completed."
            ),
            level=Level.INFO, category=Category.SYSTEM,
        )
        row = queue_email(
            staff, schedule, NotificationType.COMPLETED,
            f"completed:{schedule.pk}:{staff.pk}",
            {"base_url": base_url},
        )
        # The Chief is told in the system only - forty confirmation emails a
        # month would bury the ones that matter.
        from notifications.service import division_chiefs

        for chief in division_chiefs():
            if chief.pk == staff.pk:
                continue
            notify_bell(
                [chief],
                title=f"{staff.get_display_name()} completed {schedule.period_label}",
                message="Both the MMIA and the DTR have been submitted.",
                url=reverse("submissions:review", args=[schedule.pk, staff.pk]),
                category=Category.SYSTEM, level=Level.INFO,
                dedupe_key=f"monthly:{schedule.pk}:chief:{chief.pk}:done:{staff.pk}"[:120],
            )
        kick([row.pk] if row else [])
        return

    have = [kind for kind in DocumentKind if submission.has(kind)]
    missing = [kind for kind in DocumentKind if not submission.has(kind)]
    if have and missing:
        _bell(
            staff, schedule, "partial",
            title=f"{schedule.period_label}: {missing[0].label} still pending",
            message=(
                f"Your {have[0].label} has been submitted. "
                f"Your {missing[0].label} is still pending."
            ),
        )


def manual_reminders(rows, actor, note="", base_url=""):
    """The Chief's Send Reminder button. `rows` are services.Row objects."""
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    queued = []
    reminded = 0
    for row in rows:
        if row.standing.is_complete or not row.staff.is_active:
            continue
        schedule, person = row.schedule, row.staff
        missing = ", ".join(row.standing.missing_labels)
        _bell(
            person, schedule, f"manual:{stamp}",
            title=f"Reminder from the Division Chief: {schedule.period_label}",
            message=(note or f"Please submit your {missing} for {schedule.period_label}.")[:400],
            level=Level.URGENT if not schedule.is_open() else Level.ACTION,
        )
        email = queue_email(
            person, schedule, NotificationType.MANUAL_REMINDER,
            f"manual:{schedule.pk}:{person.pk}:{stamp}",
            {"note": note, "sent_by": actor.get_display_name(), "base_url": base_url},
        )
        if email:
            queued.append(email.pk)
        reminded += 1
    kick(queued)
    return reminded


# ---------------------------------------------------------------------------
# The scheduled run: upcoming-deadline reminders and overdue notices
# ---------------------------------------------------------------------------


def _threshold_for(schedule, at):
    """
    Which reminder is due now, if any.

    The smallest configured interval at or above the days left: with 7, 3, 1
    and 0, five days out is the 7-day reminder (sent late if the scheduler
    missed day seven) and two days out is the 3-day one. A reminder whose
    window opened before the deadline was set is skipped - the announcement
    the staff just received already says it.
    """
    days_left = schedule.days_remaining(at)
    eligible = [d for d in settings.MONTHLY_SUBMISSION_REMINDER_DAYS if d >= days_left]
    if not eligible or days_left < 0:
        return None
    threshold = min(eligible)
    window_opens = datetime.combine(
        schedule.deadline_local.date() - timedelta(days=threshold), time(0, 0),
        tzinfo=MANILA,
    )
    if schedule.deadline_set_at >= window_opens:
        return None
    return threshold


def queue_scheduled(at=None):
    """
    Queue whatever reminders and overdue notices are due at `at`.

    Safe to run as often as you like: every notice has a key, and a key that
    already exists is skipped. Returns counts for the command's report.
    """
    from .services import pending_for

    at = at or timezone.now()
    summary = {"reminders": 0, "overdue": 0}
    if at.astimezone(MANILA).hour < settings.MONTHLY_SUBMISSION_REMINDER_HOUR:
        return summary

    for schedule in MonthlySubmissionSchedule.objects.open(at):
        threshold = _threshold_for(schedule, at)
        if threshold is None:
            continue
        days_left = schedule.days_remaining(at)
        for row in pending_for(schedule, at):
            person = row.staff
            email = queue_email(
                person, schedule, NotificationType.REMINDER,
                f"reminder:{schedule.pk}:{schedule.deadline_stamp}:{threshold}:{person.pk}",
                {"stamp": schedule.deadline_stamp, "threshold": threshold},
            )
            if email is None:
                continue
            summary["reminders"] += 1
            if days_left == 0:
                remaining = "Today is the deadline"
            else:
                remaining = f"You have {days_left} day{'s' if days_left != 1 else ''} remaining"
            missing = " and ".join(row.standing.missing_labels)
            _bell(
                person, schedule, f"reminder:{schedule.deadline_stamp}:{threshold}",
                title=f"Reminder: {schedule.period_label} MMIA and DTR",
                message=f"Reminder: {remaining} to submit your {missing}.",
                level=Level.URGENT if days_left <= 1 else Level.ACTION,
            )

    window_start = at - timedelta(days=settings.MONTHLY_SUBMISSION_OVERDUE_WINDOW_DAYS)
    overdue_schedules = MonthlySubmissionSchedule.objects.filter(
        deadline__lte=at, deadline__gt=window_start
    )
    for schedule in overdue_schedules:
        for row in pending_for(schedule, at):
            person = row.staff
            email = queue_email(
                person, schedule, NotificationType.OVERDUE,
                f"overdue:{schedule.pk}:{schedule.deadline_stamp}:{person.pk}",
                {"stamp": schedule.deadline_stamp},
            )
            if email is None:
                continue
            summary["overdue"] += 1
            _bell(
                person, schedule, f"overdue:{schedule.deadline_stamp}",
                title=f"Overdue: {schedule.period_label} MMIA and DTR",
                message=(
                    "Your monthly submission deadline has passed. Please contact "
                    "your Division Chief for further instructions."
                ),
                level=Level.URGENT, category=Category.OVERDUE,
            )
    return summary


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def _sendable(now):
    retry_before = now - timedelta(minutes=settings.MONTHLY_SUBMISSION_EMAIL_RETRY_MINUTES)
    return (
        Q(email_status=EmailStatus.PENDING)
        | Q(
            email_status=EmailStatus.FAILED,
            attempts__lt=settings.MONTHLY_SUBMISSION_EMAIL_MAX_ATTEMPTS,
            last_attempt_at__lte=retry_before,
        )
        | Q(email_status=EmailStatus.SENDING, last_attempt_at__lte=now - STALE_SENDING)
    )


def _claim(pk, now):
    """Atomically take one row for sending. False if another worker has it."""
    return MonthlySubmissionNotification.objects.filter(pk=pk).filter(
        _sendable(now)
    ).update(
        email_status=EmailStatus.SENDING,
        attempts=F("attempts") + 1,
        last_attempt_at=now,
    ) == 1


def _finish(notice, status, error="", subject=""):
    notice.email_status = status
    notice.last_error = error[:255]
    if subject:
        notice.subject = subject[:200]
    fields = ["email_status", "last_error", "subject", "email_address"]
    if status == EmailStatus.SENT:
        notice.sent_at = timezone.now()
        fields.append("sent_at")
    notice.save(update_fields=fields)


def dispatch(ids=None, at=None):
    """
    Send every email that is due: new ones, and failures whose retry is due.

    Returns {"sent", "failed", "skipped"}. Never raises on an SMTP error -
    the row is marked FAILED and the next run tries again.
    """
    now = at or timezone.now()
    summary = {"sent": 0, "failed": 0, "skipped": 0}
    candidates = MonthlySubmissionNotification.objects.filter(_sendable(now))
    if ids is not None:
        candidates = candidates.filter(pk__in=ids)
    pks = list(candidates.order_by("pk").values_list("pk", flat=True))
    if not pks:
        return summary

    connection = None
    try:
        for pk in pks:
            if not _claim(pk, now):
                continue
            notice = MonthlySubmissionNotification.objects.select_related(
                "recipient", "schedule"
            ).get(pk=pk)
            notice.email_address = notice.recipient.email or ""

            try:
                built = build_email(notice, at=now)
            except Exception as exc:  # a template error must not stop the run
                logger.exception("Could not compose monthly submission email %s", pk)
                _finish(notice, EmailStatus.FAILED, f"Could not compose: {exc}")
                summary["failed"] += 1
                continue
            if isinstance(built, str):
                _finish(notice, EmailStatus.SKIPPED, built)
                summary["skipped"] += 1
                continue

            subject, text, html = built
            message = EmailMultiAlternatives(
                subject=subject, body=text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[notice.email_address],
            )
            message.attach_alternative(html, "text/html")
            try:
                if connection is None:
                    connection = get_connection(fail_silently=False)
                message.connection = connection
                message.send()
            except Exception as exc:
                logger.warning(
                    "Monthly submission email %s to %s failed: %s",
                    pk, notice.email_address, exc,
                )
                _finish(notice, EmailStatus.FAILED, str(exc) or exc.__class__.__name__,
                        subject=subject)
                summary["failed"] += 1
                # A broken SMTP session is not reused for the next message.
                try:
                    if connection is not None:
                        connection.close()
                except Exception:
                    pass
                connection = None
                continue
            _finish(notice, EmailStatus.SENT, subject=subject)
            summary["sent"] += 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return summary


# ---------------------------------------------------------------------------
# What each email says
# ---------------------------------------------------------------------------

_SIGN_OFF = [
    SYSTEM_NAME,
    AGENCY["department"],
    "Region XIII – Caraga",
]


def build_email(notice, at=None):
    """
    (subject, text, html) for a queued email, or a string giving the reason
    it should no longer be sent.
    """
    at = at or timezone.now()
    person = notice.recipient
    schedule = notice.schedule
    params = notice.params or {}
    kind = notice.notification_type

    if not person.is_active:
        return "The account is no longer active."
    if not person.email:
        return "No email address is recorded for this account."

    submission = MonthlyStaffSubmission.objects.filter(
        staff=person, schedule=schedule
    ).first()
    complete = submission is not None and submission.is_complete
    if kind != NotificationType.COMPLETED and complete:
        return "Both documents were submitted before this email went out."
    stamp = params.get("stamp")
    if stamp and stamp != schedule.deadline_stamp:
        return "The deadline has changed since this email was queued."
    if kind == NotificationType.OVERDUE and schedule.is_open(at):
        return "The deadline was extended; the submission is no longer overdue."

    link = _site_url(params.get("base_url", "")) + module_url(schedule)
    deadline = _deadline_text(schedule.deadline)
    statuses = [
        (f"{DOCUMENT_TITLES[k]} ({k.label})",
         "Submitted" if submission is not None and submission.has(k) else "Not Submitted")
        for k in DocumentKind
    ]
    missing = [k for k in DocumentKind if submission is None or not submission.has(k)]
    missing_sentence = _missing_sentence(missing)

    context = {
        "greeting": "Dear LGMED Personnel,",
        "paragraphs": [],
        "facts": [("Reporting Month", schedule.period_label)],
        "required_documents": False,
        "statuses": [],
        "announcement": "",
        "after_facts": [],
        "closing": [],
        "button_label": "Open Monthly Submissions",
        "link": link,
        "sign_off": _SIGN_OFF,
    }

    if kind == NotificationType.ANNOUNCEMENT:
        subject = f"{SYSTEM_NAME} | Monthly MMIA and DTR Submission Reminder"
        context["paragraphs"] = [
            "Please be informed that the submission deadline for your Monthly "
            "Monitoring Individual Accomplishments (MMIA) and Daily Time Record "
            "(DTR) has been established.",
        ]
        context["facts"].append(("Submission Deadline", deadline))
        context["after_facts"] = [
            "You are requested to prepare and upload both required documents "
            "through the LGMED-iMMS Monthly Submissions Module before the "
            "prescribed deadline.",
        ]
        context["required_documents"] = True
        context["announcement"] = schedule.announcement
        context["closing"] = [
            "Please access LGMED-iMMS to complete your submission.", "Thank you.",
        ]

    elif kind == NotificationType.DEADLINE_CHANGED:
        word = "Extended" if params.get("extended") else "Updated"
        subject = f"{SYSTEM_NAME} | Monthly Submission Deadline {word}"
        old = params.get("old_deadline")
        context["greeting"] = f"Dear {person.get_display_name()},"
        context["paragraphs"] = [
            f"Please be informed that the submission deadline for your MMIA and "
            f"DTR for {schedule.period_label} has been {word.lower()} by the "
            "Division Chief.",
        ]
        if old:
            context["facts"].append(
                ("Previous Deadline", _deadline_text(datetime.fromisoformat(old)))
            )
        context["facts"].append(("New Submission Deadline", deadline))
        context["statuses"] = statuses
        context["after_facts"] = [missing_sentence] if missing_sentence else []
        context["announcement"] = schedule.announcement
        context["closing"] = ["Thank you."]

    elif kind in (NotificationType.REMINDER, NotificationType.MANUAL_REMINDER):
        days_left = schedule.days_remaining(at)
        if kind == NotificationType.REMINDER:
            if days_left <= 0:
                subject = f"{SYSTEM_NAME} | MMIA and DTR Due Today"
                lead = (f"This is a reminder that your MMIA and DTR for "
                        f"{schedule.period_label} are due today.")
            else:
                plural = "s" if days_left != 1 else ""
                subject = (f"{SYSTEM_NAME} | Reminder: MMIA and DTR Due in "
                           f"{days_left} Day{plural}")
                lead = (f"This is a reminder that you have {days_left} day{plural} "
                        f"remaining to submit your MMIA and DTR for "
                        f"{schedule.period_label}.")
        else:
            subject = f"{SYSTEM_NAME} | Reminder: Pending Monthly MMIA and DTR Submission"
            lead = (f"The Division Chief has sent you a reminder about your "
                    f"{schedule.period_label} MMIA and DTR submission.")
        context["greeting"] = f"Dear {person.get_display_name()},"
        context["paragraphs"] = [lead]
        if kind == NotificationType.MANUAL_REMINDER and params.get("note"):
            context["paragraphs"].append(
                f"Message from {params.get('sent_by') or 'the Division Chief'}: "
                f"“{params['note']}”"
            )
        context["facts"].append(("Submission Deadline", deadline))
        context["statuses"] = statuses
        if schedule.is_open(at):
            context["after_facts"] = [missing_sentence]
        else:
            context["after_facts"] = [
                "The prescribed submission period has ended. Please coordinate "
                "with your Division Chief if you need to submit or update your "
                "documents."
            ]
        context["closing"] = ["Thank you."]

    elif kind == NotificationType.COMPLETED:
        if not complete:
            return "The submission is no longer complete."
        subject = f"{SYSTEM_NAME} | Monthly Submission Successfully Completed"
        context["greeting"] = f"Dear {person.get_display_name()},"
        context["paragraphs"] = [
            "Your monthly document submission has been successfully completed.",
        ]
        context["facts"] += [
            ("MMIA", "Submitted"),
            ("DTR", "Submitted"),
            ("Submission Date", _deadline_text(submission.completed_at)),
        ]
        context["after_facts"] = ["Your documents have been recorded in LGMED-iMMS."]
        context["closing"] = ["Thank you for your timely compliance."]
        context["button_label"] = "View your submission"

    elif kind == NotificationType.OVERDUE:
        subject = f"{SYSTEM_NAME} | Overdue Monthly MMIA and DTR Submission"
        context["greeting"] = f"Dear {person.get_display_name()},"
        context["paragraphs"] = [
            f"The submission deadline for your {schedule.period_label} MMIA and "
            f"DTR passed on {deadline}, and your submission is not yet complete.",
        ]
        context["facts"].append(("Submission Deadline", deadline))
        context["statuses"] = statuses
        missing_names = " and ".join(
            f"{DOCUMENT_TITLES[k]} ({k.label})" for k in missing
        )
        context["after_facts"] = [
            f"Outstanding: {missing_names}.",
            "The prescribed submission period has ended. Please coordinate with "
            "your Division Chief if you need to submit or update your documents.",
        ]
        context["closing"] = ["Thank you."]
    else:
        return f"Unknown notification type {kind}."

    context["subject"] = subject
    context["agency"] = AGENCY
    text = render_to_string("emails/submissions/notice.txt", context)
    html = render_to_string("emails/submissions/notice.html", context)
    return subject, text, html


def _missing_sentence(missing):
    if not missing:
        return ""
    if len(missing) == 1:
        kind = missing[0]
        return (
            f"Your {DOCUMENT_TITLES[kind]} ({kind.label}) is still pending. "
            "Please upload the document before the prescribed deadline."
        )
    return (
        "Your Monthly Monitoring Individual Accomplishments (MMIA) and Daily "
        "Time Record (DTR) are still pending. Please upload both documents "
        "before the prescribed deadline."
    )
