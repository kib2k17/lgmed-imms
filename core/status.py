"""
The single vocabulary of record states used across LGMED-iMMS.

Section 4 of the design system fixes four status colours; section 20 requires
that status never be communicated by colour alone. Every badge therefore pairs
a colour with a glyph, and modules map their own state values onto these keys
instead of inventing new palettes.
"""

# tone key -> presentation
STATUS_STYLES = {
    "success": {
        "label": "Completed",
        "icon": "check",
        "classes": "border-green-200 bg-green-50 text-green-800",
    },
    "warning": {
        "label": "Pending",
        "icon": "clock",
        "classes": "border-amber-200 bg-amber-50 text-amber-800",
    },
    "danger": {
        "label": "Critical",
        "icon": "warning",
        "classes": "border-red-200 bg-red-50 text-red-800",
    },
    "info": {
        "label": "In Progress",
        "icon": "info",
        "classes": "border-blue-200 bg-blue-50 text-blue-800",
    },
    "neutral": {
        "label": "Inactive",
        "icon": "close",
        "classes": "border-slate-200 bg-slate-100 text-slate-700",
    },
}

# record value -> tone key
STATUS_MAP = {
    # green
    "active": "success",
    "completed": "success",
    "approved": "success",
    "published": "success",
    "compliant": "success",
    "resolved": "success",
    "verified": "success",
    "on_track": "success",
    "reviewed": "success",
    # amber
    "pending": "warning",
    "for_review": "warning",
    "for review": "warning",
    "review_required": "warning",
    "screening": "warning",
    "draft": "warning",
    "ongoing_review": "warning",
    "partial": "warning",
    "due_soon": "warning",
    "postponed": "warning",
    "suspended": "warning",
    "open": "warning",
    "submitted": "warning",
    "for_revision": "warning",
    "for_action": "warning",
    "for_assignment": "warning",
    "for_approval": "warning",
    "for_retention_review": "warning",
    "retention_due": "warning",
    # red
    "rejected": "danger",
    "critical": "danger",
    "overdue": "danger",
    "non_compliant": "danger",
    "failed": "danger",
    "cancelled": "danger",
    "returned": "danger",
    "for_disposal": "danger",
    "disposed": "danger",
    # blue
    "in_progress": "info",
    "in progress": "info",
    # The PPA module: a file that has been scanned but not yet decided on.
    "screened": "info",
    "ongoing": "info",
    "scheduled": "info",
    "planned": "info",
    "information": "info",
    "new": "info",
    "upcoming": "info",
    "assigned": "info",
    "acknowledged": "info",
    "received": "info",
    "registered": "info",
    # slate
    "archived": "neutral",
    "unpublished": "neutral",
    "withdrawn": "neutral",
    "uploaded": "neutral",
    "inactive": "neutral",
    "closed": "neutral",
    "not_started": "neutral",
    "not_assessed": "neutral",
    "permanent": "neutral",
    # Incoming: brought in from the spreadsheet register, not yet in the workflow.
    "imported": "neutral",
}


def resolve_status(value):
    """Map any record status onto one of the five presentation tones."""
    if not value:
        return "neutral"
    key = str(value).strip().lower().replace("-", "_")
    if key in STATUS_STYLES:
        return key
    return STATUS_MAP.get(key, "neutral")
