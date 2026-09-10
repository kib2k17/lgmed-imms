"""
Analytical figures, computed from the records.

The dashboard answers "what needs my attention today". This module answers the
questions asked at a performance review: how coverage differs across the five
provinces, whether monitoring is keeping pace with last year, how long a report
takes to get from submission to publication.

Every function returns the Chart.js series *and* the same numbers as table
rows, so a figure quoted in a meeting can be read off the page without the
chart (section 20 of the design system).
"""

from django.db.models import Avg, Count, F, Q
from django.utils import timezone

from documents.models import Document, DocumentStatus
from lgus.models import LGU, ComplianceStatus, LGUType, Province
from monitoring.models import MonitoringActivity, MonitoringStatus
from programs.models import Program, ProgramCategory, ProgramStatus
from reports.models import Report, ReportStatus

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def available_years():
    """Years that actually hold monitoring records, newest first."""
    years = set(
        MonitoringActivity.objects.dates("monitoring_date", "year").values_list(
            "monitoring_date__year", flat=True
        )
    )
    years.update(
        Report.objects.values_list("year", flat=True).distinct()
    )
    years.discard(None)
    years.add(timezone.localdate().year)
    return sorted(years, reverse=True)


# ---------------------------------------------------------------------------
# Headline figures
# ---------------------------------------------------------------------------


def headline(year):
    """The four numbers a division chief asks for first."""
    activities = MonitoringActivity.objects.filter(monitoring_date__year=year)
    lgus = LGU.objects.count()
    covered = (
        LGU.objects.filter(monitoring_activities__monitoring_date__year=year)
        .distinct()
        .count()
    )
    published = Report.objects.filter(
        status=ReportStatus.PUBLISHED, published_on__year=year
    ).count()

    return {
        "activities": activities.count(),
        "lgus_total": lgus,
        "lgus_covered": covered,
        "coverage_percent": round(covered * 100 / lgus) if lgus else 0,
        "completed_percent": (
            round(
                activities.filter(status=MonitoringStatus.COMPLETED).count()
                * 100
                / activities.count()
            )
            if activities.count()
            else 0
        ),
        "published_reports": published,
        "turnaround": report_turnaround(year),
    }


def report_turnaround(year):
    """
    Average days from submission to publication.

    Only reports that completed the journey in this year are counted; a report
    still sitting in review would otherwise flatter or distort the average
    depending on which way you squint at it.
    """
    completed = Report.objects.filter(
        status=ReportStatus.PUBLISHED,
        published_on__year=year,
        submitted_on__isnull=False,
        published_on__isnull=False,
    )
    result = completed.annotate(
        days=F("published_on") - F("submitted_on")
    ).aggregate(average=Avg("days"))["average"]

    if result is None:
        return None
    # SQLite returns a number of days; PostgreSQL returns a timedelta.
    return round(getattr(result, "days", result))


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def monitoring_by_province(year):
    provinces = list(Province.objects.order_by("name"))
    labels, conducted, covered, totals = [], [], [], []

    for province in provinces:
        lgus_in_province = LGU.objects.filter(province=province)
        labels.append(province.name)
        totals.append(lgus_in_province.count())
        conducted.append(
            MonitoringActivity.objects.filter(
                lgu__province=province, monitoring_date__year=year
            ).count()
        )
        covered.append(
            lgus_in_province.filter(
                monitoring_activities__monitoring_date__year=year
            )
            .distinct()
            .count()
        )

    return {
        "id": "monitoringByProvince",
        "title": "Monitoring by Province",
        "subtitle": f"Activities conducted and LGUs reached in {year}.",
        "span": 2,
        "has_data": any(conducted),
        "data": {"labels": labels, "conducted": conducted, "covered": covered,
                 "total": totals},
        "headers": ["Province", "Activities", "LGUs reached", "LGUs", "Coverage"],
        "rows": [
            [
                label,
                activity_count,
                reached,
                total,
                f"{round(reached * 100 / total)}%" if total else "0%",
            ]
            for label, activity_count, reached, total in zip(
                labels, conducted, covered, totals
            )
        ],
    }


def compliance_breakdown():
    counts = LGU.objects.aggregate(
        **{
            value.lower(): Count("pk", filter=Q(compliance_status=value))
            for value, _label in ComplianceStatus.choices
        }
    )
    labels = [label for _value, label in ComplianceStatus.choices]
    values = [counts[value.lower()] for value, _label in ComplianceStatus.choices]
    total = sum(values)

    return {
        "id": "complianceBreakdown",
        "title": "LGU Compliance",
        "subtitle": f"Assessed status across {total} local government units.",
        "span": 1,
        "has_data": total > 0,
        "data": {"labels": labels, "values": values},
        "headers": ["Status", "LGUs", "Share"],
        "rows": [
            [label, value, f"{round(value * 100 / total)}%" if total else "0%"]
            for label, value in zip(labels, values)
        ],
    }


def monitoring_trend(year):
    """This year against last, so a shortfall is visible while it can be fixed."""
    def per_month(target_year):
        counts = [0] * 12
        for value in MonitoringActivity.objects.filter(
            monitoring_date__year=target_year
        ).values_list("monitoring_date", flat=True):
            counts[value.month - 1] += 1
        return counts

    current = per_month(year)
    previous = per_month(year - 1)

    return {
        "id": "monitoringTrend",
        "title": "Monitoring Trend",
        "subtitle": f"{year} compared with {year - 1}, month by month.",
        "span": 2,
        "has_data": any(current) or any(previous),
        "data": {"labels": MONTHS, "current": current, "previous": previous,
                 "currentLabel": str(year), "previousLabel": str(year - 1)},
        "headers": ["Month", str(year), str(year - 1), "Change"],
        "rows": [
            [
                month,
                now,
                before,
                ("+" if now - before > 0 else "") + str(now - before),
            ]
            for month, now, before in zip(MONTHS, current, previous)
        ],
    }


def programs_by_category():
    rows = (
        ProgramCategory.objects.annotate(
            total=Count("programs"),
            active=Count("programs", filter=Q(programs__status=ProgramStatus.ACTIVE)),
        )
        .filter(total__gt=0)
        .order_by("-total", "name")
    )
    labels = [row.name for row in rows]
    active = [row.active for row in rows]
    other = [row.total - row.active for row in rows]

    return {
        "id": "programsByCategory",
        "title": "Programs by Category",
        "subtitle": "Active programs against the rest of the register.",
        "span": 1,
        "has_data": bool(labels),
        "data": {"labels": labels, "active": active, "other": other},
        "headers": ["Category", "Active", "Other", "Total"],
        "rows": [
            [label, a, o, a + o] for label, a, o in zip(labels, active, other)
        ],
    }


def lgu_type_coverage(year):
    labels, covered, totals = [], [], []
    for value, label in LGUType.choices:
        of_type = LGU.objects.filter(lgu_type=value)
        labels.append(label)
        totals.append(of_type.count())
        covered.append(
            of_type.filter(monitoring_activities__monitoring_date__year=year)
            .distinct()
            .count()
        )

    return {
        "id": "lguTypeCoverage",
        "title": "Coverage by LGU Type",
        "subtitle": f"LGUs with at least one monitoring activity in {year}.",
        "span": 1,
        "has_data": any(totals),
        "data": {"labels": labels, "covered": covered, "total": totals},
        "headers": ["LGU type", "Reached", "Registered", "Coverage"],
        "rows": [
            [
                label,
                reached,
                total,
                f"{round(reached * 100 / total)}%" if total else "0%",
            ]
            for label, reached, total in zip(labels, covered, totals)
        ],
    }


def report_pipeline(year):
    counts = Report.objects.filter(year=year).aggregate(
        **{
            value.lower(): Count("pk", filter=Q(status=value))
            for value, _label in ReportStatus.choices
        }
    )
    labels = [label for _value, label in ReportStatus.choices]
    values = [counts[value.lower()] for value, _label in ReportStatus.choices]

    return {
        "id": "reportPipeline",
        "title": "Report Pipeline",
        "subtitle": f"Where the {year} reports currently stand.",
        "span": 2,
        "has_data": any(values),
        "data": {"labels": labels, "values": values},
        "headers": ["Stage", "Reports"],
        "rows": [[label, value] for label, value in zip(labels, values)],
    }


def charts(year):
    return [
        monitoring_by_province(year),
        compliance_breakdown(),
        monitoring_trend(year),
        lgu_type_coverage(year),
        programs_by_category(),
        report_pipeline(year),
    ]


# ---------------------------------------------------------------------------
# Least-covered LGUs - the operational point of the whole page
# ---------------------------------------------------------------------------


def least_monitored(year, limit=10):
    """
    LGUs with the fewest monitoring activities this year.

    The most useful thing on the page: it names the LGUs the Division has not
    reached, in the order it should reach them.
    """
    return (
        LGU.objects.select_related("province")
        .annotate(
            visits=Count(
                "monitoring_activities",
                filter=Q(monitoring_activities__monitoring_date__year=year),
            )
        )
        .order_by("visits", "province__name", "name")[:limit]
    )


def document_summary(year):
    documents = Document.objects.filter(year=year)
    return {
        "total": documents.count(),
        "completed": documents.filter(status=DocumentStatus.COMPLETED).count(),
        "public": documents.public().count(),
    }
