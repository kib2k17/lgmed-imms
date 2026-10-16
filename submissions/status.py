"""
A staff member's standing for a reporting month, worked out on demand.

Four states, and each person is in exactly one of them, so dashboard figures
add up to the number of staff without anyone being counted twice:

    COMPLETED      both the MMIA and the DTR are in - whenever that was
    OVERDUE        the deadline has passed and at least one is missing
    PARTIAL        before the deadline, one of the two is in
    NOT_SUBMITTED  before the deadline, neither is in

OVERDUE takes precedence over PARTIAL and NOT_SUBMITTED once the deadline has
passed; `missing` still says which document is outstanding.
"""

from dataclasses import dataclass, field

from django.utils import timezone

from .models import DOCUMENT_TITLES, DocumentKind

NOT_SUBMITTED = "not_submitted"
PARTIAL = "partial"
COMPLETED = "completed"
OVERDUE = "overdue"

STATUS_ORDER = (NOT_SUBMITTED, PARTIAL, COMPLETED, OVERDUE)

LABELS = {
    NOT_SUBMITTED: "Not Submitted",
    PARTIAL: "Incomplete Submission",
    COMPLETED: "Submission Completed",
    OVERDUE: "Overdue Submission",
}

# Short forms for table cells and filters.
SHORT_LABELS = {
    NOT_SUBMITTED: "Not Submitted",
    PARTIAL: "Incomplete",
    COMPLETED: "Completed",
    OVERDUE: "Overdue",
}

# Keys of core/status.py's shared vocabulary: gray, amber, green, red.
TONES = {
    NOT_SUBMITTED: "neutral",
    PARTIAL: "warning",
    COMPLETED: "success",
    OVERDUE: "danger",
}


@dataclass
class Standing:
    status: str
    submitted: list = field(default_factory=list)
    missing: list = field(default_factory=list)

    @property
    def label(self):
        return LABELS[self.status]

    @property
    def short_label(self):
        return SHORT_LABELS[self.status]

    @property
    def tone(self):
        return TONES[self.status]

    @property
    def uploaded_count(self):
        return len(self.submitted)

    @property
    def percent(self):
        return round(len(self.submitted) * 100 / len(DocumentKind))

    @property
    def is_complete(self):
        return self.status == COMPLETED

    @property
    def missing_labels(self):
        return [DocumentKind(kind).label for kind in self.missing]

    @property
    def missing_titles(self):
        return [
            f"{DOCUMENT_TITLES[DocumentKind(kind)]} ({DocumentKind(kind).label})"
            for kind in self.missing
        ]


def standing(schedule, submission=None, at=None):
    """The standing of one submission (or none at all) against its schedule."""
    at = at or timezone.now()
    submitted = [
        kind.value for kind in DocumentKind
        if submission is not None and submission.has(kind)
    ]
    missing = [kind.value for kind in DocumentKind if kind.value not in submitted]

    if not missing:
        status = COMPLETED
    elif not schedule.is_open(at):
        status = OVERDUE
    elif submitted:
        status = PARTIAL
    else:
        status = NOT_SUBMITTED
    return Standing(status=status, submitted=submitted, missing=missing)
