"""
Dashboard figures, computed from the records themselves.

This replaces the Phase 1 `core.demo` placeholder module: every number below
is a query against real data, so the dashboard is trustworthy enough to put in
front of the Regional Director. Where there is nothing to count, the figure is
zero and the panel says so rather than inventing a plausible number.
"""

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from activities.models import CalendarActivity
from documents.models import Document, DocumentStatus
from incoming.models import IncomingDocument, IncomingStatus
from lgus.models import LGU, LGUType
from monitoring.models import MonitoringActivity, MonitoringStatus
from programs.models import Program, ProgramStatus
from reports.models import Report, ReportStatus

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PENDING_REPORT_STATUSES = (
    ReportStatus.DRAFT,
    ReportStatus.SUBMITTED,
    ReportStatus.FOR_REVIEW,
    ReportStatus.RETURNED,
)


def summary_cards():
    """The six figures required by section 9 of the design system."""
    year = timezone.localdate().year
    programs = Program.objects.all()
    lgus = LGU.objects.all()
    reports = Report.objects.all()

    lgu_breakdown = lgus.aggregate(
        provinces=Count("pk", filter=Q(lgu_type=LGUType.PROVINCE)),
        cities=Count("pk", filter=Q(lgu_type=LGUType.CITY)),
        municipalities=Count("pk", filter=Q(lgu_type=LGUType.MUNICIPALITY)),
    )
    categories = programs.values("category").distinct().count()

    return [
        {
            "label": "Total Programs",
            "value": programs.count(),
            "meta": f"Across {categories} program categor{'y' if categories == 1 else 'ies'}",
            "icon": "programs",
            "url_name": "programs:list",
        },
        {
            "label": "Active Programs",
            "value": programs.filter(status=ProgramStatus.ACTIVE).count(),
            "meta": "Currently being implemented",
            "icon": "check-circle",
            "tone": "success",
            "url_name": "programs:list",
        },
        {
            "label": "Monitoring Activities",
            "value": MonitoringActivity.objects.filter(
                monitoring_date__year=year
            ).count(),
            "meta": f"Conducted in {year}",
            "icon": "monitoring",
            "url_name": "monitoring:list",
        },
        {
            "label": "Registered LGUs",
            "value": lgus.count(),
            "meta": (
                f"{lgu_breakdown['provinces']} provinces, "
                f"{lgu_breakdown['cities']} cities, "
                f"{lgu_breakdown['municipalities']} municipalities"
            ),
            "icon": "lgu",
            "url_name": "lgus:list",
        },
        {
            "label": "Pending Reports",
            "value": reports.filter(status__in=PENDING_REPORT_STATUSES).count(),
            "meta": "Awaiting submission, review or approval",
            "icon": "clock",
            "tone": "warning",
            "url_name": "reports:list",
        },
        {
            "label": "Published Reports",
            "value": reports.filter(status=ReportStatus.PUBLISHED).count(),
            "meta": "Available to LGUs and the public",
            "icon": "reports",
            "tone": "success",
            "url_name": "reports:list",
        },
    ]


# ---------------------------------------------------------------------------
# Charts
#
# Each returns the Chart.js series *and* the same numbers as table rows, so the
# figures are available without sight of the canvas (section 20).
# ---------------------------------------------------------------------------


def _monthly_counts(queryset, date_field, year):
    """Count rows per month for the given year, as a 12-slot list."""
    counts = [0] * 12
    rows = (
        queryset.filter(**{f"{date_field}__year": year})
        .values_list(date_field, flat=True)
    )
    for value in rows:
        if value:
            counts[value.month - 1] += 1
    return counts


def program_status_chart():
    counts = Program.objects.aggregate(
        active=Count("pk", filter=Q(status=ProgramStatus.ACTIVE)),
        completed=Count("pk", filter=Q(status=ProgramStatus.COMPLETED)),
        pending=Count("pk", filter=Q(status=ProgramStatus.PENDING)),
        archived=Count("pk", filter=Q(status=ProgramStatus.ARCHIVED)),
    )
    labels = ["Active", "Completed", "Pending", "Archived"]
    values = [counts["active"], counts["completed"],
              counts["pending"], counts["archived"]]
    total = sum(values)

    return {
        "id": "programStatus",
        "title": "Program Status",
        "subtitle": (
            f"Distribution across {total} registered program{'s' if total != 1 else ''}."
        ),
        "span": 1,
        "has_data": total > 0,
        "data": {"labels": labels, "values": values},
        "headers": ["Status", "Programs", "Share"],
        "rows": [
            [label, value, f"{round(value * 100 / total)}%" if total else "0%"]
            for label, value in zip(labels, values)
        ],
    }


def monitoring_activity_chart():
    year = timezone.localdate().year
    values = _monthly_counts(MonitoringActivity.objects.all(), "monitoring_date", year)
    return {
        "id": "monitoringActivity",
        "title": "Monitoring Activities",
        "subtitle": f"Activities conducted per month in {year}.",
        "span": 2,
        "has_data": any(values),
        "data": {"labels": MONTHS, "values": values},
        "headers": ["Month", "Activities"],
        "rows": [[month, value] for month, value in zip(MONTHS, values)],
    }


def lgu_monitoring_chart():
    year = timezone.localdate().year
    labels, monitored, totals = [], [], []

    for value, label in LGUType.choices:
        of_type = LGU.objects.filter(lgu_type=value)
        labels.append(label)
        totals.append(of_type.count())
        monitored.append(
            of_type.filter(monitoring_activities__monitoring_date__year=year)
            .distinct()
            .count()
        )

    return {
        "id": "lguMonitoring",
        "title": "LGU Monitoring Coverage",
        "subtitle": f"LGUs monitored in {year} against the total registered.",
        "span": 1,
        "has_data": any(totals),
        "data": {"labels": labels, "monitored": monitored, "total": totals},
        "headers": ["LGU type", "Monitored", "Registered", "Coverage"],
        "rows": [
            [label, done, total, f"{round(done * 100 / total)}%" if total else "0%"]
            for label, done, total in zip(labels, monitored, totals)
        ],
    }


def report_submission_chart():
    year = timezone.localdate().year
    submitted = _monthly_counts(Report.objects.all(), "submitted_on", year)
    published = _monthly_counts(Report.objects.all(), "published_on", year)
    return {
        "id": "reportSubmissions",
        "title": "Report Submissions",
        "subtitle": f"Reports submitted and published per month in {year}.",
        "span": 2,
        "has_data": any(submitted) or any(published),
        "data": {"labels": MONTHS, "submitted": submitted, "published": published},
        "headers": ["Month", "Submitted", "Published"],
        "rows": [
            [month, s, p] for month, s, p in zip(MONTHS, submitted, published)
        ],
    }


def charts():
    return [
        program_status_chart(),
        monitoring_activity_chart(),
        lgu_monitoring_chart(),
        report_submission_chart(),
    ]


# ---------------------------------------------------------------------------
# Operational lists
# ---------------------------------------------------------------------------


def recent_monitoring(limit=5):
    return (
        MonitoringActivity.objects.select_related("lgu", "lgu__province")
        .order_by("-monitoring_date", "-id")[:limit]
    )


def pending_actions():
    """Work that is waiting on somebody - the reason to open the dashboard."""
    today = timezone.localdate()

    for_review = MonitoringActivity.objects.filter(status=MonitoringStatus.FOR_REVIEW)
    oldest = for_review.order_by("monitoring_date").first()

    unpublished = Document.objects.filter(
        status__in=(DocumentStatus.DRAFT, DocumentStatus.FOR_REVIEW)
    )
    overdue = MonitoringActivity.objects.filter(
        follow_up_date__lt=today
    ).exclude(status__in=(MonitoringStatus.COMPLETED, MonitoringStatus.CANCELLED))

    pending_reports = Report.objects.filter(status__in=PENDING_REPORT_STATUSES)
    incoming_for_review = IncomingDocument.objects.for_review()
    oldest_incoming = incoming_for_review.order_by("date_received").first()
    incoming_overdue = IncomingDocument.objects.overdue(today)

    items = [
        {
            "label": "Incoming documents awaiting Division Chief review",
            "count": incoming_for_review.count(),
            "detail": (
                f"Oldest received {date_format(oldest_incoming.date_received, 'j M Y')}"
                if oldest_incoming
                else "Nothing awaiting review"
            ),
            "status": "for_review",
            "url": (
                f"{reverse('incoming:list')}?status={IncomingStatus.FOR_REVIEW}"
            ),
        },
        {
            "label": "Incoming documents overdue",
            "count": incoming_overdue.count(),
            "detail": "Past their action due date",
            "status": "overdue",
            "url": f"{reverse('incoming:list')}?view=overdue",
        },
        {
            "label": "Monitoring records awaiting review",
            "count": for_review.count(),
            "detail": (
                f"Oldest dated {date_format(oldest.monitoring_date, 'j M Y')}"
                if oldest else "Nothing awaiting review"
            ),
            "status": "for_review",
            "url": f"{reverse('monitoring:list')}?status={MonitoringStatus.FOR_REVIEW}",
        },
        {
            "label": "Documents awaiting review",
            "count": unpublished.count(),
            "detail": f"{unpublished.filter(status=DocumentStatus.DRAFT).count()} still in draft",
            "status": "pending",
            "url": f"{reverse('documents:list')}?status={DocumentStatus.FOR_REVIEW}",
        },
        {
            "label": "Follow-up actions overdue",
            "count": overdue.count(),
            "detail": "Past their follow-up date",
            "status": "overdue",
            "url": reverse("monitoring:list"),
        },
        {
            "label": "Reports awaiting action",
            "count": pending_reports.count(),
            "detail": "Draft, submitted or for review",
            "status": "submitted",
            "url": reverse("reports:list"),
        },
    ]
    return [item for item in items if item["count"]]


def upcoming_activities(user, limit=5):
    """
    What is next, for whoever is looking.

    Scoped through `visible_to` like every other calendar query: the dashboard
    is a summary of the system, not a way around its permissions, and an
    employee's private plan has no business appearing on a colleague's home
    page because the widget forgot to ask whose it was.
    """
    return (
        CalendarActivity.objects.visible_to(user)
        .with_people()
        .upcoming()
        .order_by("start_date", "start_time")[:limit]
    )


# ---------------------------------------------------------------------------
# Public website
# ---------------------------------------------------------------------------


def public_summary():
    """Headline figures for the public homepage."""
    lgus = LGU.objects.all()
    return {
        "lgus": lgus.count(),
        "provinces": lgus.filter(lgu_type=LGUType.PROVINCE).count(),
        "cities": lgus.filter(lgu_type=LGUType.CITY).count(),
        "municipalities": lgus.filter(lgu_type=LGUType.MUNICIPALITY).count(),
        "programs": Program.objects.filter(status=ProgramStatus.ACTIVE).count(),
        "monitoring": MonitoringActivity.objects.filter(
            monitoring_date__year=timezone.localdate().year
        ).count(),
        "reports": Report.objects.filter(status=ReportStatus.PUBLISHED).count(),
        "documents": Document.objects.public().count(),
    }


def public_documents(limit=5):
    return (
        Document.objects.public()
        .select_related("document_type")
        .order_by("-year", "-created_at")[:limit]
    )


def public_activities(limit=4):
    """
    Published, office-wide and still ahead. See `core.views.public_calendar`
    for why the visibility level is checked alongside the published flag.
    """
    from activities.models import ActivityStatus, Visibility

    return (
        CalendarActivity.objects.filter(
            is_published=True,
            visibility=Visibility.ORGANIZATION,
            start_date__gte=timezone.localdate(),
        )
        .exclude(status=ActivityStatus.CANCELLED)
        .order_by("start_date", "start_time")[:limit]
    )


def public_services(limit=6):
    from services.models import FrontlineService

    return FrontlineService.objects.filter(is_published=True).order_by("name")[:limit]


def public_news(limit=4):
    """Latest published news items for the homepage feed."""
    from announcements.models import Announcement

    return Announcement.objects.published().news()[:limit]


def public_featured_story():
    """
    The item an officer has pinned to the homepage, if there is one.

    Queried separately from the feed rather than picked out of it: a
    commendation worth featuring is often older than the last week's
    activities, and would otherwise fall off the end of the list it was
    supposed to lead.
    """
    from announcements.models import Announcement

    return Announcement.objects.published().news().filter(is_featured=True).first()


def public_commendations(limit=6):
    from announcements.models import Announcement

    return Announcement.objects.published().commendations()[:limit]


def public_statistics():
    """
    The regional picture in figures, for the public Statistics page.

    Everything here is counted from the records, so a figure that reads zero
    means nothing has been encoded yet - not that the page is broken.
    """
    year = timezone.localdate().year
    lgus = LGU.objects.all()
    monitoring = MonitoringActivity.objects.all()

    provinces = list(
        lgus.filter(lgu_type=LGUType.PROVINCE)
        .order_by("name")
        .values_list("name", flat=True)
    )

    by_province = (
        lgus.exclude(lgu_type=LGUType.PROVINCE)
        .values("province__name")
        .annotate(
            cities=Count("pk", filter=Q(lgu_type=LGUType.CITY)),
            municipalities=Count("pk", filter=Q(lgu_type=LGUType.MUNICIPALITY)),
            total=Count("pk"),
        )
        .order_by("province__name")
    )

    monitoring_by_status = [
        {
            "label": label,
            "count": monitoring.filter(
                status=value, monitoring_date__year=year
            ).count(),
        }
        for value, label in MonitoringStatus.choices
    ]

    programs_by_category = list(
        Program.objects.values("category__name")
        .annotate(total=Count("pk"))
        .order_by("-total", "category__name")
    )

    documents_by_type = list(
        Document.objects.public()
        .values("document_type__name")
        .annotate(total=Count("pk"))
        .order_by("-total", "document_type__name")
    )

    return {
        "year": year,
        "provinces": provinces,
        "by_province": list(by_province),
        "monitoring_by_status": monitoring_by_status,
        "monitoring_this_year": monitoring.filter(monitoring_date__year=year).count(),
        "programs_by_category": programs_by_category,
        "documents_by_type": documents_by_type,
        "lgus_covered": monitoring.filter(monitoring_date__year=year)
        .values("lgu").distinct().count(),
    }
