"""
The monitoring reports, described once and driven by one view.

Each report is a title, a short statement of what it answers, and a function
that turns a filtered queryset into headers and rows. Both the page and the CSV
export read the same structure, so the file an officer downloads holds exactly
the figures they were looking at - which is the only way a report is worth
attaching to a memorandum.

Two shapes of report:

  document reports  one row per document, for working through
  summary reports   one row per focal person or status, for reporting upward
"""

from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    UPDATE_REMINDER_DAYS,
    IncomingDocument,
    IncomingStatus,
    OPEN_STATUSES,
)


def _date(value, fmt="%d %b %Y"):
    if not value:
        return ""
    if hasattr(value, "hour"):
        value = timezone.localtime(value)
    return value.strftime(fmt)


def _person(user):
    return user.get_display_name() if user else "Unassigned"


def _days(value):
    return "" if value is None else str(value)


def _average(values):
    numbers = [v for v in values if v is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 1)


# ---------------------------------------------------------------------------
# Document reports - one row per document
# ---------------------------------------------------------------------------

DOCUMENT_HEADERS = [
    "LGMED code", "DNS number", "Subject", "Document type", "Source / office",
    "Date received", "Status", "Priority", "Focal person", "Date assigned",
    "Due date", "Date completed",
]


def _document_row(document):
    return [
        document.lgmed_code or "",
        document.docket_number,
        document.subject,
        document.document_type.name,
        document.source_office,
        _date(document.date_received),
        document.display_status_label,
        document.get_priority_display(),
        _person(document.assigned_to),
        _date(document.assigned_at),
        _date(document.due_date),
        _date(document.completed_at),
    ]


def _documents(queryset):
    return {
        "headers": DOCUMENT_HEADERS,
        "rows": [_document_row(document) for document in queryset],
    }


def _for_review(queryset):
    rows = queryset.for_review()
    today = timezone.localdate()
    return {
        "headers": [
            "DNS number", "Subject", "Document type", "Source / office",
            "Date received", "Days waiting", "Recorded by",
        ],
        "rows": [
            [
                document.docket_number,
                document.subject,
                document.document_type.name,
                document.source_office,
                _date(document.date_received),
                str((today - document.date_received).days),
                _person(document.created_by),
            ]
            for document in rows
        ],
    }


def _pending(queryset):
    rows = queryset.open().exclude(status=IncomingStatus.FOR_REVIEW)
    return {
        "headers": [
            "LGMED code", "DNS number", "Subject", "Status", "Focal person",
            "Date received", "Date assigned", "Due date", "Days open",
        ],
        "rows": [
            [
                document.lgmed_code or "",
                document.docket_number,
                document.subject,
                document.display_status_label,
                _person(document.assigned_to),
                _date(document.date_received),
                _date(document.assigned_at),
                _date(document.due_date),
                _days(document.days_open),
            ]
            for document in rows
        ],
    }


def _overdue(queryset):
    rows = queryset.overdue()
    return {
        "headers": [
            "DNS number", "Subject", "Focal person", "Status", "Due date",
            "Days overdue", "Last update", "Priority",
        ],
        "rows": [
            [
                document.docket_number,
                document.subject,
                _person(document.assigned_to),
                document.get_status_display(),
                _date(document.due_date),
                str(document.days_overdue),
                _date(document.latest_update.created_at)
                if document.latest_update
                else "No update recorded",
                document.get_priority_display(),
            ]
            for document in rows
        ],
    }


def _completed(queryset):
    rows = queryset.completed()
    return {
        "headers": [
            "DNS number", "Subject", "Focal person", "Date received",
            "Date assigned", "Date completed", "Days to complete", "Updates",
        ],
        "rows": [
            [
                document.docket_number,
                document.subject,
                _person(document.assigned_to),
                _date(document.date_received),
                _date(document.assigned_at),
                _date(document.completed_at),
                _days(document.days_to_complete),
                str(document.update_count),
            ]
            for document in rows
        ],
    }


def _response(queryset):
    """What each open document's focal person has said, and how long ago."""
    rows = queryset.open().filter(assigned_to__isnull=False)
    return {
        "headers": [
            "DNS number", "Subject", "Focal person", "Status",
            "Acknowledged", "Updates", "Latest action", "Last update",
            "Days since update",
        ],
        "rows": [
            [
                document.docket_number,
                document.subject,
                _person(document.assigned_to),
                document.display_status_label,
                _date(document.acknowledged_at) or "Not acknowledged",
                str(document.update_count),
                (document.latest_update.action_taken
                 if document.latest_update else "No update recorded"),
                _date(document.latest_update.created_at)
                if document.latest_update
                else "",
                _days(document.days_since_last_update),
            ]
            for document in rows
        ],
    }


def _processing_time(queryset):
    rows = list(
        queryset.exclude(status__in=(IncomingStatus.FOR_REVIEW, IncomingStatus.IMPORTED))
    )
    body = [
        [
            document.docket_number,
            document.subject,
            _person(document.assigned_to),
            _date(document.date_received),
            _days(document.days_to_assign),
            _days(document.days_to_acknowledge),
            _days(document.days_to_complete),
            document.display_status_label,
        ]
        for document in rows
    ]
    averages = [
        _average([d.days_to_assign for d in rows]),
        _average([d.days_to_acknowledge for d in rows]),
        _average([d.days_to_complete for d in rows]),
    ]
    return {
        "headers": [
            "DNS number", "Subject", "Focal person", "Date received",
            "Days to assign", "Days to acknowledge", "Days to complete", "Status",
        ],
        "rows": body,
        "footer": (
            ["Average", "", "", ""]
            + [_days(value) for value in averages]
            + [""]
        )
        if rows
        else None,
    }


def _assignment(queryset):
    rows = queryset.filter(assigned_to__isnull=False)
    return {
        "headers": [
            "DNS number", "Subject", "Assigned to", "Assigned by",
            "Date assigned", "Acknowledged", "Instructions", "Status",
        ],
        "rows": [
            [
                document.docket_number,
                document.subject,
                _person(document.assigned_to),
                _person(document.assigned_by),
                _date(document.assigned_at),
                _date(document.acknowledged_at) or "Not acknowledged",
                document.assignment_remarks or document.review_notes,
                document.display_status_label,
            ]
            for document in rows
        ],
    }


# ---------------------------------------------------------------------------
# Summary reports - one row per focal person or status
# ---------------------------------------------------------------------------


def _by_focal_person(queryset):
    """
    A workload picture: how much each officer holds and how much is late.

    Overdue is counted in Python rather than in the aggregate because "overdue"
    depends on today's date and on the record not being finished - a condition
    the model already states once, and which should not be restated in SQL
    where it can drift.
    """
    today = timezone.localdate()
    documents = list(queryset.select_related("assigned_to").prefetch_related("updates"))

    buckets = {}
    for document in documents:
        key = document.assigned_to_id
        bucket = buckets.setdefault(
            key,
            {
                "person": _person(document.assigned_to),
                "total": 0, "open": 0, "overdue": 0, "completed": 0,
                "unacknowledged": 0, "silent": 0,
            },
        )
        bucket["total"] += 1
        if document.is_completed:
            bucket["completed"] += 1
        else:
            bucket["open"] += 1
            if document.is_overdue:
                bucket["overdue"] += 1
            if document.awaits_acknowledgement:
                bucket["unacknowledged"] += 1
            days = document.days_since_last_update
            if document.is_assigned and (days is None or days >= UPDATE_REMINDER_DAYS):
                bucket["silent"] += 1

    rows = sorted(buckets.values(), key=lambda b: (-b["total"], b["person"]))
    return {
        "headers": [
            "Focal person", "Total", "Open", "Awaiting acknowledgement",
            "Awaiting update", "Overdue", "Completed",
        ],
        "rows": [
            [
                bucket["person"],
                str(bucket["total"]),
                str(bucket["open"]),
                str(bucket["unacknowledged"]),
                str(bucket["silent"]),
                str(bucket["overdue"]),
                str(bucket["completed"]),
            ]
            for bucket in rows
        ],
        "footer": [
            "Total",
            str(sum(b["total"] for b in rows)),
            str(sum(b["open"] for b in rows)),
            str(sum(b["unacknowledged"] for b in rows)),
            str(sum(b["silent"] for b in rows)),
            str(sum(b["overdue"] for b in rows)),
            str(sum(b["completed"] for b in rows)),
        ]
        if rows
        else None,
    }


def _by_status(queryset):
    counts = dict(
        queryset.values_list("status").annotate(total=Count("pk")).values_list(
            "status", "total"
        )
    )
    total = sum(counts.values())
    rows = [
        [
            label,
            str(counts.get(value, 0)),
            f"{(counts.get(value, 0) / total * 100):.1f}%" if total else "0.0%",
        ]
        for value, label in IncomingStatus.choices
    ]
    return {
        "headers": ["Status", "Documents", "Share"],
        "rows": rows,
        "footer": ["Total", str(total), "100.0%"] if total else None,
    }


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

REPORTS = {
    "incoming": {
        "label": "Incoming Documents Report",
        "description": "Every document received, with where it now stands.",
        "build": _documents,
    },
    "for-review": {
        "label": "Documents for Division Chief Review",
        "description": "Recorded but not yet reviewed and assigned.",
        "build": _for_review,
    },
    "by-focal-person": {
        "label": "Documents by Focal Person",
        "description": "Workload and outstanding items for each officer.",
        "build": _by_focal_person,
    },
    "by-status": {
        "label": "Documents by Status",
        "description": "How the caseload is distributed across the workflow.",
        "build": _by_status,
    },
    "pending": {
        "label": "Pending Documents Report",
        "description": "Assigned and unfinished, whatever the stage.",
        "build": _pending,
    },
    "overdue": {
        "label": "Overdue Documents Report",
        "description": "Past the action due date and still outstanding.",
        "build": _overdue,
    },
    "completed": {
        "label": "Completed Documents Report",
        "description": "Closed documents and how long each one took.",
        "build": _completed,
    },
    "response": {
        "label": "Response / Action Monitoring Report",
        "description": "The latest action on each open document, and its age.",
        "build": _response,
    },
    "processing-time": {
        "label": "Processing Time Report",
        "description": "Days to assign, to acknowledge and to complete.",
        "build": _processing_time,
    },
    "assignment": {
        "label": "Assignment Monitoring Report",
        "description": "Who assigned what to whom, and whether it was acknowledged.",
        "build": _assignment,
    },
}

DEFAULT_REPORT = "incoming"


def get_report(slug):
    return REPORTS.get(slug) or REPORTS[DEFAULT_REPORT]


def catalogue():
    return [{"slug": slug, **spec} for slug, spec in REPORTS.items()]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

SORTS = {
    "date_received": "Date received (oldest first)",
    "-date_received": "Date received (newest first)",
    "docket_number": "DNS number",
    "subject": "Subject",
    "status": "Status",
    "assigned_to__last_name": "Focal person",
    "due_date": "Due date",
    "-completed_at": "Date completed",
}
DEFAULT_SORT = "-date_received"


def filtered_queryset(params):
    """
    The documents a report covers, narrowed by the toolbar above it.

    Returns the queryset and a readable description of what was applied, so the
    page and the exported file can both say what they are showing.
    """
    queryset = IncomingDocument.objects.select_related(
        "document_type", "assigned_to", "assigned_by", "created_by", "reviewed_by"
    ).prefetch_related("updates")
    applied = []

    term = (params.get("q") or "").strip()
    if term:
        queryset = queryset.filter(
            Q(docket_number__icontains=term)
            | Q(lgmed_code__icontains=term)
            | Q(subject__icontains=term)
            | Q(source_office__icontains=term)
        )
        applied.append(f'Search "{term}"')

    start = (params.get("from") or "").strip()
    end = (params.get("to") or "").strip()
    if start:
        queryset = queryset.filter(date_received__gte=start)
    if end:
        queryset = queryset.filter(date_received__lte=end)
    if start or end:
        applied.append(f"Received {start or 'any'} to {end or 'any'}")

    focal = (params.get("focal") or "").strip()
    if focal == "unassigned":
        queryset = queryset.filter(assigned_to__isnull=True)
        applied.append("Unassigned")
    elif focal.isdigit():
        queryset = queryset.filter(assigned_to_id=int(focal))
        applied.append("Focal person selected")

    status = (params.get("status") or "").strip()
    if status == "OPEN":
        queryset = queryset.filter(status__in=OPEN_STATUSES)
        applied.append("Open documents only")
    elif status in IncomingStatus.values:
        queryset = queryset.filter(status=status)
        applied.append(f"Status {IncomingStatus(status).label}")

    document_type = (params.get("type") or "").strip()
    if document_type.isdigit():
        queryset = queryset.filter(document_type_id=int(document_type))
        applied.append("Document type selected")

    sort = params.get("sort") or DEFAULT_SORT
    if sort not in SORTS:
        sort = DEFAULT_SORT
    queryset = queryset.order_by(sort, "-id")

    return queryset, applied, sort
