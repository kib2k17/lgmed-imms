"""
Who gets told what, and when.

Two kinds of notification, because they answer different questions:

  * Event notifications fire the moment something happens - a report is
    submitted for review, an account's role changes. They are raised from
    signals, so they cannot be forgotten by a view that took a shortcut.

  * Standing conditions - an overdue follow-up, a document that has sat
    unpublished - are not events at all. Nothing "happens" on the day a
    follow-up becomes overdue, so these are found by `refresh_standing_notices`,
    run on a schedule. A `dedupe_key` keeps a three-week-old problem from
    producing twenty-one identical notifications.

A notification is always addressed to a person, never to a role, so an unread
count means "things you have not dealt with".
"""

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User

from .models import Category, Level, Notification


# ---------------------------------------------------------------------------
# Audiences
# ---------------------------------------------------------------------------


def _active(queryset):
    return queryset.filter(is_active=True)


def approvers():
    """Those who can move a report or document to published."""
    return _active(
        User.objects.filter(
            Q(is_superuser=True)
            | Q(role__in=(Role.SUPERADMIN, Role.ADMIN, Role.LGMED_STAFF))
        )
    ).distinct()


def administrators():
    return _active(
        User.objects.filter(
            Q(is_superuser=True) | Q(role__in=(Role.SUPERADMIN, Role.ADMIN))
        )
    ).distinct()


def encoders():
    """Everyone who maintains records - the audience for overdue work."""
    return _active(
        User.objects.filter(
            Q(is_superuser=True)
            | Q(role__in=(Role.SUPERADMIN, Role.ADMIN, Role.LGMED_STAFF, Role.ENCODER))
        )
    ).distinct()


# ---------------------------------------------------------------------------
# Raising notifications
# ---------------------------------------------------------------------------


def notify(recipients, *, title, message="", url="", category=Category.SYSTEM,
           level=Level.INFO, dedupe_key="", exclude=None):
    """
    Create a notification for each recipient, skipping duplicates.

    `exclude` drops one user from the audience - normally the person who caused
    the event, who does not need telling about their own action.
    """
    created = []
    excluded_pk = getattr(exclude, "pk", None)

    for recipient in recipients:
        if recipient.pk == excluded_pk:
            continue
        if dedupe_key and Notification.objects.filter(
            recipient=recipient, dedupe_key=dedupe_key, dismissed_at__isnull=True
        ).exists():
            continue
        created.append(
            Notification.objects.create(
                recipient=recipient,
                title=title[:200],
                message=message[:400],
                url=url[:255],
                category=category,
                level=level,
                dedupe_key=dedupe_key[:120],
            )
        )
    return created


def resolve(dedupe_key):
    """
    Withdraw notifications for a condition that no longer holds.

    When a report is finally approved, the "awaiting review" notice should
    disappear rather than sit unread forever. Withdrawn notices are dismissed,
    not deleted, so the audit trail of what people were told stays intact.
    """
    return Notification.objects.filter(
        dedupe_key=dedupe_key, dismissed_at__isnull=True
    ).update(dismissed_at=timezone.now(), read_at=timezone.now())


# ---------------------------------------------------------------------------
# Standing conditions
# ---------------------------------------------------------------------------


def division_chiefs():
    """Those who may review an incoming document and assign its focal person."""
    from accounts.capabilities import users_with

    return users_with("can_review_incoming")


def refresh_standing_notices():
    """
    Find work that is waiting and tell the people who can act on it.

    Safe to run repeatedly: existing conditions are deduplicated, and
    conditions that have since been resolved are withdrawn. Returns a count
    per condition so the command can report what it did.
    """
    from documents import workflow as documents_workflow
    from incoming import workflow as incoming_workflow
    from monitoring.models import MonitoringActivity, MonitoringStatus
    from reports.models import Report, ReportStatus

    today = timezone.localdate()
    summary = {"raised": 0, "withdrawn": 0}

    # -- monitoring follow-ups past their due date ----------------------
    overdue = MonitoringActivity.objects.filter(
        follow_up_date__lt=today
    ).exclude(
        status__in=(MonitoringStatus.COMPLETED, MonitoringStatus.CANCELLED)
    ).select_related("lgu")

    overdue_keys = set()
    for activity in overdue:
        key = f"monitoring:overdue:{activity.pk}"
        overdue_keys.add(key)
        days = (today - activity.follow_up_date).days
        summary["raised"] += len(
            notify(
                encoders(),
                title=f"Follow-up overdue: {activity.lgu.name}",
                message=(
                    f"{activity.title} - follow-up was due "
                    f"{activity.follow_up_date:%d %b %Y}, {days} day"
                    f"{'s' if days != 1 else ''} ago."
                ),
                url=activity.get_absolute_url(),
                category=Category.OVERDUE,
                level=Level.URGENT if days > 14 else Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- reports waiting on a reviewer -----------------------------------
    awaiting = Report.objects.filter(
        status__in=(ReportStatus.SUBMITTED, ReportStatus.FOR_REVIEW)
    )
    review_keys = set()
    for report in awaiting:
        key = f"report:review:{report.pk}"
        review_keys.add(key)
        summary["raised"] += len(
            notify(
                approvers(),
                title=f"Report awaiting review: {report.title}",
                message=(
                    f"{report.get_period_display()} {report.year}"
                    + (
                        f", submitted {report.submitted_on:%d %b %Y}"
                        if report.submitted_on
                        else ""
                    )
                ),
                url=report.get_absolute_url(),
                category=Category.REVIEW,
                level=Level.ACTION,
                dedupe_key=key,
            )
        )

    # -- withdraw notices whose condition has gone away -------------------
    live = overdue_keys | review_keys
    stale = (
        Notification.objects.filter(dismissed_at__isnull=True)
        .filter(
            Q(dedupe_key__startswith="monitoring:overdue:")
            | Q(dedupe_key__startswith="report:review:")
        )
        .exclude(dedupe_key__in=live)
    )
    summary["withdrawn"] = stale.update(
        dismissed_at=timezone.now(), read_at=timezone.now()
    )

    # -- incoming documents, and the document register ---------------------
    #
    # Kept in their own modules rather than restated here: the conditions
    # ("nothing heard for a week", "past its action due date", "its retention
    # period has run out") are each module's own definitions, and a second copy
    # of them would be a second copy to get wrong.
    for module in (incoming_workflow, documents_workflow):
        result = module.refresh_standing_notices()
        summary["raised"] += result["raised"]
        summary["withdrawn"] += result["withdrawn"]
    return summary
