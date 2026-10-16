"""
The fixed vocabularies of the module: the Organizational Outcomes, the status
and risk scales, the document kinds, what may be uploaded - and the reference
table of programme categories.

Part of programs.models - see its package docstring.
"""

from django.db import models
from django.utils.text import slugify


# ---------------------------------------------------------------------------
# What may be uploaded
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png")
DOCUMENT_EXTENSIONS = ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx")
ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS + IMAGE_EXTENSIONS

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


# ---------------------------------------------------------------------------
# The Department's five Organizational Outcomes
# ---------------------------------------------------------------------------


class OrganizationalOutcome(models.TextChoices):
    """
    The five outcomes every DILG programme reports against.

    Fixed in code rather than kept in a table because they are not this
    office's to invent: they come from the Department's results framework, the
    public website groups its whole programme listing by them, and a
    mis-spelled sixth outcome created one afternoon would sit there unnoticed.
    """

    OO1 = "OO1", "Excellence in Local Governance Upheld"
    OO2 = "OO2", "Peaceful, Orderly, Safe, and Secure Communities Strengthened"
    OO3 = "OO3", "Resilient Communities Reinforced"
    OO4 = "OO4", "Inclusive Communities Enabled"
    OO5 = "OO5", "Highly Trusted Department and Partner"


# Presentation detail for each outcome: the number as the office says it, a
# short handle for cards and filters, the slug the public URL uses, and the
# sentence that explains the outcome to a visitor who has never read the
# results framework.
OUTCOME_DETAIL = {
    OrganizationalOutcome.OO1: {
        "number": 1,
        "short_label": "Excellence in Local Governance",
        "slug": "excellence-in-local-governance",
        "icon": "programs",
        "summary": (
            "Local governments that plan, budget, deliver and account for "
            "services well - and are assessed, assisted and recognised for it."
        ),
    },
    OrganizationalOutcome.OO2: {
        "number": 2,
        "short_label": "Peaceful, Orderly and Safe Communities",
        "slug": "peaceful-orderly-safe-communities",
        "icon": "monitoring",
        "summary": (
            "Peace and order, public safety and anti-illegal drug efforts "
            "carried out with local government units and their councils."
        ),
    },
    OrganizationalOutcome.OO3: {
        "number": 3,
        "short_label": "Resilient Communities",
        "slug": "resilient-communities",
        "icon": "warning",
        "summary": (
            "Disaster preparedness, risk reduction and climate adaptation "
            "built into the way local governments plan and spend."
        ),
    },
    OrganizationalOutcome.OO4: {
        "number": 4,
        "short_label": "Inclusive Communities",
        "slug": "inclusive-communities",
        "icon": "users",
        "summary": (
            "Participation, representation and services that reach women, "
            "children, indigenous peoples, older persons and the sectors most "
            "often left out."
        ),
    },
    OrganizationalOutcome.OO5: {
        "number": 5,
        "short_label": "Highly Trusted Department",
        "slug": "highly-trusted-department",
        "icon": "check-circle",
        "summary": (
            "The Department's own integrity, transparency and service "
            "standards - how it is trusted by the publics it serves."
        ),
    },
}

OUTCOME_BY_SLUG = {
    detail["slug"]: outcome for outcome, detail in OUTCOME_DETAIL.items()
}


def outcome_detail(value):
    """Presentation detail for an outcome value, safe for an unknown value."""
    return OUTCOME_DETAIL.get(
        value,
        {
            "number": 0,
            "short_label": str(value),
            "slug": slugify(str(value)),
            "icon": "programs",
            "summary": "",
        },
    )


# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------


class ProgramStatus(models.TextChoices):
    """
    How the *work* is going.

    Kept apart from the publication lifecycle below, and the separation is the
    point: a completed project whose report has not been cleared is completed
    and unpublished, and a system with one status field forces somebody to lie
    about one of those two things.
    """

    PENDING = "PENDING", "Pending"
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    SUSPENDED = "SUSPENDED", "Suspended"
    ARCHIVED = "ARCHIVED", "Archived"


# The same vocabulary reads better under this name below the programme level.
ImplementationStatus = ProgramStatus


class PublicationStatus(models.TextChoices):
    """
    Where a record stands on its way to the public website.

    DRAFT            being written; nobody outside the encoder need look yet
    FOR_REVIEW       handed to a reviewer, nothing flagged by the screening
    SCREENING        the attached files are being scanned; a transient state
    REVIEW_REQUIRED  the screening flagged something, or could not read a file
    APPROVED         a reviewer has read it and cleared the content
    PUBLISHED        live on the public website
    UNPUBLISHED      taken down; it was public once, and is not now
    ARCHIVED         closed out, kept for the record, not public
    """

    DRAFT = "DRAFT", "Draft"
    FOR_REVIEW = "FOR_REVIEW", "For review"
    SCREENING = "SCREENING", "Screening in progress"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "Review required"
    APPROVED = "APPROVED", "Approved"
    PUBLISHED = "PUBLISHED", "Published"
    UNPUBLISHED = "UNPUBLISHED", "Unpublished"
    ARCHIVED = "ARCHIVED", "Archived"


# States from which an encoder may hand work to a reviewer.
SUBMITTABLE_STATUSES = (
    PublicationStatus.DRAFT,
    PublicationStatus.REVIEW_REQUIRED,
    PublicationStatus.UNPUBLISHED,
)

# States a reviewer may act on.
REVIEWABLE_STATUSES = (
    PublicationStatus.FOR_REVIEW,
    PublicationStatus.SCREENING,
    PublicationStatus.REVIEW_REQUIRED,
)

# States an encoder may still edit without going back through review. Editing
# approved or published content returns it to the queue; see `touch_content`.
EDITABLE_WITHOUT_REREVIEW = (
    PublicationStatus.DRAFT,
    PublicationStatus.REVIEW_REQUIRED,
    PublicationStatus.UNPUBLISHED,
)

# Everything a reviewer or publisher still has business with. Archived records
# are excluded from the working lists but never deleted.
OPEN_STATUSES = tuple(
    s for s in PublicationStatus.values if s != PublicationStatus.ARCHIVED
)


class RiskLevel(models.TextChoices):
    """
    What the automated screening found in a file.

    Three levels on purpose. A reviewer facing a queue has to be able to tell
    at a glance which files need their full attention, and a scale with more
    gradations than that gets read as noise.
    """

    LOW = "LOW", "Low risk"
    REVIEW_REQUIRED = "REVIEW_REQUIRED", "Review required"
    HIGH = "HIGH", "High risk"


class DocumentStatus(models.TextChoices):
    """Where one uploaded file stands."""

    UPLOADED = "UPLOADED", "Uploaded - internal"
    SCREENING = "SCREENING", "Screening"
    SCREENED = "SCREENED", "Screened - awaiting review"
    APPROVED = "APPROVED", "Approved for publication"
    REJECTED = "REJECTED", "Rejected"
    FOR_REVISION = "FOR_REVISION", "Revision requested"
    PUBLISHED = "PUBLISHED", "Published"
    WITHDRAWN = "WITHDRAWN", "Withdrawn from the public website"


#: The statuses in which a reviewer's clearance of a file still stands, and so
#: the statuses from which the file may be put on the public website.
#:
#: WITHDRAWN belongs here, and that is the whole of the fix for republishing.
#: Withdrawal is a *publication* act taken by a publisher - the file comes off
#: the website and its public copy is destroyed - and it says nothing at all
#: about the review. The approval that put the file there is still on the row:
#: `withdraw` touches neither `reviewed_by`, `reviewed_at` nor
#: `review_comments`, and a file can only reach WITHDRAWN by way of PUBLISHED,
#: which can only be reached from APPROVED. So a withdrawn file is a file a
#: reviewer has cleared, which a publisher has chosen not to show.
#:
#: Reading it as unapproved - which is what every predicate here used to do -
#: made withdrawal a dead end: the only route back onto the website was a
#: second trip through the reviewer's decision form, and that is why putting a
#: document or photograph back took several confirmations instead of one.
#:
#: REJECTED is deliberately absent. That is a reviewer saying no, and it stays
#: the route for a file that must not go out again.
RELEASABLE_STATUSES = (
    DocumentStatus.APPROVED,
    DocumentStatus.PUBLISHED,
    DocumentStatus.WITHDRAWN,
)

#: Cleared, and not on the public website at this moment: one publisher action
#: away from it. The difference from RELEASABLE_STATUSES is PUBLISHED, which is
#: already there and has nothing to wait for.
AWAITING_RELEASE_STATUSES = (
    DocumentStatus.APPROVED,
    DocumentStatus.WITHDRAWN,
)


class DocumentKind(models.TextChoices):
    """What the file is, said in the office's own words."""

    ISSUANCE = "ISSUANCE", "Issuance or memorandum"
    REPORT = "REPORT", "Report or accomplishment record"
    GUIDELINE = "GUIDELINE", "Guidelines or primer"
    PRESENTATION = "PRESENTATION", "Presentation"
    PHOTO = "PHOTO", "Photograph"
    CERTIFICATE = "CERTIFICATE", "Certificate"
    OTHER = "OTHER", "Other supporting file"


# ---------------------------------------------------------------------------
# Reference data carried over from the first version of this module
# ---------------------------------------------------------------------------


class ProgramCategory(models.Model):
    """Reference list of program categories, editable in System Settings."""

    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "program categories"
        ordering = ("name",)

    def __str__(self):
        return self.name
