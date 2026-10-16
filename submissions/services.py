"""
What the Monthly Submissions module does, separate from how it is shown.

The views only collect input and render; uploading, setting a deadline and
writing the trail all happen here, so the rules hold the same way whether an
action arrives from a page, from the JSON upload endpoint or from a test.
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from audit.models import Action
from audit.recording import client_ip, record

from . import notify
from .models import (
    MANILA,
    AuditAction,
    DocumentKind,
    MonthlyStaffSubmission,
    MonthlySubmissionAuditLog,
    MonthlySubmissionSchedule,
)
from .status import COMPLETED, OVERDUE, PARTIAL, NOT_SUBMITTED, STATUS_ORDER, standing
from .validators import clean_display_name

logger = logging.getLogger(__name__)


class UploadClosed(Exception):
    """The schedule's deadline has passed; nothing more may be uploaded."""


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


def log(action, *, user=None, schedule=None, staff=None, kind="", details="",
        request=None):
    """Write one entry to the module's trail. Never raises."""
    try:
        return MonthlySubmissionAuditLog.objects.create(
            user=user,
            user_label=user.get_display_name() if user is not None else "System",
            action=action,
            schedule=schedule,
            staff=staff,
            document_kind=DocumentKind(kind).value if kind else "",
            details=details[:500],
            ip_address=client_ip(request),
        )
    except Exception:  # pragma: no cover - a trail failure must not fail the action
        logger.exception("Could not write monthly submission audit entry %s", action)
        return None


def format_deadline(value):
    local = value.astimezone(MANILA)
    return f"{local:%B} {local.day}, {local.year}, at {local:%I:%M %p}".replace(" 0", " ")


# ---------------------------------------------------------------------------
# Who submits, and where everyone stands
# ---------------------------------------------------------------------------


def submitters():
    """Every active account required to submit an MMIA and DTR."""
    return User.objects.filter(
        is_active=True,
        is_superuser=False,
        role__in=settings.MONTHLY_SUBMISSION_SUBMITTER_ROLES,
    ).order_by("last_name", "first_name", "username")


@dataclass
class Row:
    schedule: MonthlySubmissionSchedule
    staff: User
    submission: MonthlyStaffSubmission | None
    standing: object

    @property
    def key(self):
        return f"{self.schedule.pk}:{self.staff.pk}"

    @property
    def submitted_on(self):
        return self.submission.completed_at if self.submission else None

    @property
    def last_activity(self):
        return self.submission.last_uploaded_at if self.submission else None

    def has(self, kind):
        return self.submission is not None and self.submission.has(kind)

    @property
    def has_mmia(self):
        return self.has(DocumentKind.MMIA)

    @property
    def has_dtr(self):
        return self.has(DocumentKind.DTR)


def monitoring_rows(schedules, at=None):
    """
    One row per required staff member per schedule.

    Staff who are no longer required to submit - moved to another role, or
    deactivated - still appear for the months in which they did hand
    something in, so a past month's record does not change after the fact.
    """
    at = at or timezone.now()
    schedules = list(schedules)
    if not schedules:
        return []
    staff = list(submitters())
    staff_ids = {person.pk for person in staff}
    submissions = MonthlyStaffSubmission.objects.filter(
        schedule__in=schedules
    ).select_related("staff", "staff__section")
    by_key = {(item.schedule_id, item.staff_id): item for item in submissions}
    former = {}
    for item in submissions:
        if item.staff_id not in staff_ids:
            former[item.staff_id] = item.staff

    rows = []
    for schedule in schedules:
        people = staff + [
            person for pk, person in former.items() if (schedule.pk, pk) in by_key
        ]
        for person in people:
            submission = by_key.get((schedule.pk, person.pk))
            rows.append(Row(schedule, person, submission,
                            standing(schedule, submission, at)))
    return rows


def summarise(rows):
    """Counts per status. Every row is in exactly one status."""
    counts = {status: 0 for status in STATUS_ORDER}
    for row in rows:
        counts[row.standing.status] += 1
    total = len(rows)
    return {
        "total": total,
        "completed": counts[COMPLETED],
        "partial": counts[PARTIAL],
        "not_submitted": counts[NOT_SUBMITTED],
        "overdue": counts[OVERDUE],
        "percent": round(counts[COMPLETED] * 100 / total) if total else 0,
    }


def pending_for(schedule, at=None):
    """The rows for a schedule that still have something missing."""
    return [
        row for row in monitoring_rows([schedule], at)
        if not row.standing.is_complete and row.staff.is_active
    ]


def submission_for(staff, schedule):
    return MonthlyStaffSubmission.objects.filter(
        staff=staff, schedule=schedule
    ).first()


def default_schedule_for_staff(at=None):
    """
    The reporting month a staff member is shown first.

    The current calendar month's schedule if the Chief has set one and it is
    still open; otherwise the open schedule that falls due soonest; otherwise
    the most recent schedule of all.
    """
    at = at or timezone.now()
    today = at.astimezone(MANILA).date()
    open_schedules = MonthlySubmissionSchedule.objects.open(at).order_by("deadline")
    current = open_schedules.filter(
        reporting_year=today.year, reporting_month=today.month
    ).first()
    return (
        current
        or open_schedules.first()
        or MonthlySubmissionSchedule.objects.order_by(
            "-reporting_year", "-reporting_month"
        ).first()
    )


def default_schedule_for_chief(at=None):
    """The current month's schedule, else the next open one, else the latest."""
    return default_schedule_for_staff(at)


# ---------------------------------------------------------------------------
# Setting and changing the deadline
# ---------------------------------------------------------------------------


def base_url_of(request):
    return request.build_absolute_uri("/").rstrip("/") if request else ""


def create_schedule(cleaned, actor, request=None):
    """Set a reporting month's deadline and announce it to every staff member."""
    with transaction.atomic():
        schedule = MonthlySubmissionSchedule.objects.create(
            reporting_year=cleaned["reporting_year"],
            reporting_month=cleaned["reporting_month"],
            deadline=cleaned["deadline"],
            announcement=cleaned.get("announcement", "").strip(),
            deadline_set_at=timezone.now(),
            created_by=actor,
            updated_by=actor,
        )
        log(
            AuditAction.SCHEDULE_CREATED, user=actor, schedule=schedule,
            details=f"Deadline for {schedule.period_label} set to "
                    f"{format_deadline(schedule.deadline)}.",
            request=request,
        )
        record(
            Action.CREATE, target=schedule, actor=actor, request=request,
            detail=f"Monthly submission deadline: {format_deadline(schedule.deadline)}",
        )
        base_url = base_url_of(request)
        transaction.on_commit(lambda: notify.announce(schedule, base_url=base_url))
    return schedule


def update_schedule(schedule, cleaned, actor, request=None):
    """
    Change or extend a deadline, or reword the announcement.

    Returns "extended", "changed" or "" (announcement only). A changed
    deadline restarts the reminder cycle and tells every staff member who
    has not yet completed.
    """
    with transaction.atomic():
        schedule = MonthlySubmissionSchedule.objects.select_for_update().get(
            pk=schedule.pk
        )
        old_deadline = schedule.deadline
        new_deadline = cleaned["deadline"]
        old_announcement = schedule.announcement
        new_announcement = cleaned.get("announcement", "").strip()

        change = ""
        if new_deadline != old_deadline:
            change = "extended" if new_deadline > old_deadline else "changed"
            schedule.deadline = new_deadline
            schedule.deadline_set_at = timezone.now()
        schedule.announcement = new_announcement
        schedule.updated_by = actor
        schedule.save()

        if change:
            log(
                AuditAction.DEADLINE_EXTENDED if change == "extended"
                else AuditAction.DEADLINE_CHANGED,
                user=actor, schedule=schedule,
                details=f"{schedule.period_label} deadline moved from "
                        f"{format_deadline(old_deadline)} to "
                        f"{format_deadline(new_deadline)}.",
                request=request,
            )
            record(
                Action.UPDATE, target=schedule, actor=actor, request=request,
                detail=f"Deadline {change}: {format_deadline(old_deadline)} -> "
                       f"{format_deadline(new_deadline)}",
            )
            base_url = base_url_of(request)
            extended = change == "extended"
            transaction.on_commit(lambda: notify.deadline_changed(
                schedule, old_deadline, extended=extended, base_url=base_url,
            ))
        if new_announcement != old_announcement:
            log(
                AuditAction.ANNOUNCEMENT_UPDATED, user=actor, schedule=schedule,
                details=f"Announcement for {schedule.period_label} updated.",
                request=request,
            )
    return schedule, change


# ---------------------------------------------------------------------------
# Uploading
# ---------------------------------------------------------------------------


def _locked_submission(staff, schedule):
    try:
        with transaction.atomic():
            MonthlyStaffSubmission.objects.get_or_create(staff=staff, schedule=schedule)
    except IntegrityError:
        pass  # created by a request that got there first
    return MonthlyStaffSubmission.objects.select_for_update().get(
        staff=staff, schedule=schedule
    )


def upload(staff, schedule, kind, uploaded, request=None):
    """
    Store one of the two documents for `staff`, replacing any earlier copy.

    The deadline is re-read under a row lock, so an upload that started a
    second before the deadline and a Chief shortening it at the same moment
    cannot both win. Returns (submission, replaced, became_complete).
    """
    kind = DocumentKind(kind)
    storage = MonthlyStaffSubmission._meta.get_field(f"{kind.value}_file").storage
    new_name = ""
    try:
        with transaction.atomic():
            schedule = MonthlySubmissionSchedule.objects.select_for_update().get(
                pk=schedule.pk
            )
            if not schedule.is_open():
                raise UploadClosed()
            submission = _locked_submission(staff, schedule)

            fieldfile = submission.file_for(kind)
            old_name = fieldfile.name or ""
            old_display = submission.original_name(kind)
            display = clean_display_name(uploaded.name)
            now = timezone.now()

            fieldfile.save(display, uploaded, save=False)
            new_name = fieldfile.name
            setattr(submission, f"{kind.value}_original_name", display)
            setattr(submission, f"{kind.value}_size", uploaded.size)
            setattr(submission, f"{kind.value}_uploaded_at", now)

            became_complete = submission.is_complete and submission.completed_at is None
            if became_complete:
                submission.completed_at = now
            submission.save()

            replaced = bool(old_name)
            log(
                AuditAction.REPLACED if replaced else AuditAction.UPLOADED,
                user=staff, schedule=schedule, staff=staff, kind=kind,
                details=(
                    f"{kind.label} for {schedule.period_label}: {display}"
                    + (f" (replaced {old_display})" if replaced else "")
                ),
                request=request,
            )
            record(
                Action.UPLOAD, target=submission, actor=staff, request=request,
                detail=f"{'Replaced' if replaced else 'Uploaded'} {kind.label} "
                       f"for {schedule.period_label}",
            )
            if became_complete:
                log(
                    AuditAction.COMPLETED, user=staff, schedule=schedule,
                    staff=staff,
                    details=f"MMIA and DTR for {schedule.period_label} complete.",
                    request=request,
                )
            if old_name:
                transaction.on_commit(lambda: _delete_quietly(storage, old_name))

            base_url = base_url_of(request)
            transaction.on_commit(lambda: notify.submission_progress(
                submission, became_complete=became_complete, base_url=base_url,
            ))
    except Exception:
        # The file reached the disk but the record did not: remove it, so
        # protected storage holds nothing the database does not know about.
        if new_name:
            _delete_quietly(storage, new_name)
        raise
    return submission, replaced, became_complete


def _delete_quietly(storage, name):
    try:
        storage.delete(name)
    except Exception:  # pragma: no cover
        logger.warning("Could not remove superseded submission file %s", name)


def refuse(staff, schedule, kind, reason, request=None):
    """Record an upload that was turned away, and why."""
    log(
        AuditAction.UPLOAD_REFUSED, user=staff, schedule=schedule, staff=staff,
        kind=kind if kind in DocumentKind.values else "", details=reason,
        request=request,
    )
