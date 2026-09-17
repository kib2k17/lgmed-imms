"""
Programs, Projects and Activities - what the Division delivers, and what the
public is allowed to read about it.

Two ideas hold this module together.

**The work is a tree.** Every programme the Division runs answers to one of the
Department's five Organizational Outcomes; a programme is delivered through
projects, a project through sub-projects, and the visible unit of work at the
bottom of all of it is an activity. Recording it that way is not filing for its
own sake: it is the only way a regional office can say what an Outcome actually
amounted to on the ground this year.

**Nothing is public until a person says so.** The records here describe public
work, but the papers behind them - attendance sheets, validation reports,
letters - routinely carry names, addresses, government ID numbers and
signatures. So an uploaded file is internal, always, and stays internal in a
directory no web server maps to a URL. It reaches the public website only after
an automated screening has been read by an authorised reviewer, that reviewer
has approved it, and a publisher has created a *separate public copy* of it.

The automated screening is a screening, not a decision. A clean result means
nothing was found, which is not the same as nothing being there, and the code
below never treats it as an approval.
"""

import logging
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.models import TimeStampedModel

from .storage import protected_storage

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


# ---------------------------------------------------------------------------
# The shared behaviour of every level of the tree
# ---------------------------------------------------------------------------


PUBLIC_HEADING_DEFAULTS = {
    "about": "About",
    "objectives": "Objectives",
    "accomplishment": "Accomplishment",
    "photographs": "Photographs",
    "projects": "Projects",
    "sub_projects": "Sub-projects",
    "activities": "Activities",
}
"""
The wording each section of a public record page carries unless a record says
otherwise.

Every heading on a public detail page is overridable per record, because the
same page shape carries very different work: one programme's prose section is
an "About", the next one's is a "Legal basis", and a Division that cannot say
so on the page ends up saying it in the body text instead. The defaults here
are what a record gets for leaving the field blank, which is what nearly all
of them will do - the override exists for the record that needs it, not as a
question every encoder has to answer.
"""


def heading_field(key, verbose_name):
    """An optional override for one section heading on the public page."""
    return models.CharField(
        verbose_name,
        max_length=60,
        blank=True,
        help_text=(
            f"Shown on the public website. Leave blank for "
            f"“{PUBLIC_HEADING_DEFAULTS[key]}”."
        ),
    )


class PPAQuerySet(models.QuerySet):
    """Filters every level of the tree shares."""

    def published(self):
        return self.filter(publication_status=PublicationStatus.PUBLISHED)

    def open(self):
        """Everything still in play - the working lists exclude the archive."""
        return self.exclude(publication_status=PublicationStatus.ARCHIVED)

    def awaiting_review(self):
        return self.filter(publication_status__in=REVIEWABLE_STATUSES)

    def ready_to_publish(self):
        return self.filter(publication_status=PublicationStatus.APPROVED)


class PPARecord(TimeStampedModel):
    """
    One node of the programme tree, whichever level it sits at.

    Holds the description, the office answerable for it, the implementation
    status, and the whole publication lifecycle - who submitted it, who
    reviewed it and what they said, who approved it, who published it and
    when it came down again. Section 13 of the module brief asks for exactly
    that record, and keeping it in fields on the row rather than only in the
    audit log means the answer to "who cleared this?" is on the page a
    reviewer is already looking at.
    """

    title = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        help_text="Written for the public. Do not include personal details.",
    )

    # -- what the public page calls each section ------------------------
    #
    # Wording only. These never change which sections appear, what goes in
    # them or who may see them - a heading override cannot put an unapproved
    # file on the page, and a blank one is not an empty heading but the
    # default.

    about_heading = heading_field("about", "description heading")
    photographs_heading = heading_field("photographs", "photographs heading")

    responsible_office = models.ForeignKey(
        "accounts.Section",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name="responsible office / division",
        help_text="The unit answerable for this record.",
    )
    focal_person = models.CharField(
        max_length=150,
        blank=True,
        help_text="Internal reference only; never shown on the public website.",
    )

    status = models.CharField(
        "implementation status",
        max_length=20,
        choices=ProgramStatus.choices,
        default=ProgramStatus.PENDING,
        db_index=True,
    )

    # -- publication ----------------------------------------------------

    publication_status = models.CharField(
        max_length=20,
        choices=PublicationStatus.choices,
        default=PublicationStatus.DRAFT,
        db_index=True,
    )
    slug = models.SlugField(
        max_length=280,
        unique=True,
        blank=True,
        help_text="Used in the public web address. Never a database number.",
    )
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    review_comments = models.TextField(
        blank=True,
        help_text="The reviewer's remarks. Internal.",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    unpublished_at = models.DateTimeField(null=True, blank=True)
    unpublished_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    objects = PPAQuerySet.as_manager()

    class Meta:
        abstract = True

    def __str__(self):
        return self.title

    # -- naming ---------------------------------------------------------

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def public_heading(self, key):
        """What the public page calls one of this record's sections."""
        override = (getattr(self, f"{key}_heading", "") or "").strip()
        return override or PUBLIC_HEADING_DEFAULTS[key]

    def _unique_slug(self):
        base = slugify(self.title)[:240] or "record"
        candidate = base
        model = type(self)
        suffix = 2
        while model.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    # -- where it sits in the tree --------------------------------------
    #
    # Each concrete model answers these. They let the workbench, the review
    # screen and the public pages treat any level of the tree the same way.

    level_label = "Record"
    level_key = "record"

    @property
    def parent(self):
        return None

    @property
    def outcome(self):
        """The Organizational Outcome this record ultimately answers to."""
        parent = self.parent
        return parent.outcome if parent is not None else None

    @property
    def ancestors(self):
        """Root-first chain above this record, for breadcrumbs."""
        chain = []
        node = self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    # -- publication state ----------------------------------------------

    @property
    def is_published(self):
        return self.publication_status == PublicationStatus.PUBLISHED

    @property
    def is_archived(self):
        return self.publication_status == PublicationStatus.ARCHIVED

    @property
    def parent_is_published(self):
        """
        A child is only ever as public as the record above it.

        Enforced when publishing and again when the public pages query, so a
        project cannot be reached by URL after its programme is withdrawn.
        """
        parent = self.parent
        return parent is None or parent.is_published

    @property
    def can_be_submitted(self):
        return self.publication_status in SUBMITTABLE_STATUSES

    @property
    def can_be_reviewed(self):
        return self.publication_status in REVIEWABLE_STATUSES

    @property
    def can_be_published(self):
        return (
            self.publication_status == PublicationStatus.APPROVED
            and self.parent_is_published
        )

    @property
    def blocking_documents(self):
        """Attached files a reviewer has not finished with."""
        return self.documents.filter(
            status__in=(
                DocumentStatus.UPLOADED,
                DocumentStatus.SCREENING,
                DocumentStatus.SCREENED,
            )
        )

    @property
    def flagged_documents(self):
        """Attached files the screening had something to say about."""
        return self.documents.exclude(risk_level=RiskLevel.LOW).exclude(
            status__in=(DocumentStatus.REJECTED, DocumentStatus.WITHDRAWN)
        )

    @property
    def public_documents(self):
        """The approved public copies - the only files a visitor may reach."""
        return self.documents.filter(status=DocumentStatus.PUBLISHED)

    @property
    def document_count(self):
        """
        How many files are attached, preferring a count the query already did.

        The workbench draws several hundred rows and each one shows this, so a
        page that asked the database per row would issue a query per row. The
        annotation is called `document_total` rather than `document_count`
        because a Django annotation is assigned with `setattr`, and assigning
        over a property raises.
        """
        total = self.__dict__.get("document_total")
        return total if total is not None else self.documents.count()

    # -- transitions ----------------------------------------------------
    #
    # Every transition is a method rather than an assignment so that the
    # provenance fields cannot be forgotten, and so the view layer reads as a
    # sequence of decisions rather than of database writes.

    def submit_for_review(self, user):
        """
        Hand the record to a reviewer, screening the attached files on the way.

        The screening runs here rather than at upload time because this is the
        moment the file is being offered for release, and a file uploaded
        weeks ago should be screened against today's rules.
        """
        from . import screening

        self.publication_status = PublicationStatus.SCREENING
        self.submitted_at = timezone.now()
        self.submitted_by = user
        self.updated_by = user
        self.save()

        flagged = False
        for document in self.documents.filter(
            status__in=(DocumentStatus.UPLOADED, DocumentStatus.SCREENING)
        ):
            screening.screen_document(document)
            flagged = flagged or document.risk_level != RiskLevel.LOW

        self.publication_status = (
            PublicationStatus.REVIEW_REQUIRED if flagged
            else PublicationStatus.FOR_REVIEW
        )
        self.save(update_fields=["publication_status", "updated_at"])
        return self.publication_status

    def approve(self, user, comments=""):
        """Clear the content. Does not make anything public on its own."""
        self.publication_status = PublicationStatus.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = user
        self.approved_at = timezone.now()
        self.approved_by = user
        if comments:
            self.review_comments = comments
        self.updated_by = user
        self.save()

    def request_revision(self, user, comments=""):
        """Send it back with remarks. The encoder may edit and resubmit."""
        self.publication_status = PublicationStatus.REVIEW_REQUIRED
        self.reviewed_at = timezone.now()
        self.reviewed_by = user
        self.review_comments = comments
        self.approved_at = None
        self.approved_by = None
        self.updated_by = user
        self.save()

    def reject(self, user, comments=""):
        """Refuse the content outright. It returns to draft."""
        self.publication_status = PublicationStatus.DRAFT
        self.reviewed_at = timezone.now()
        self.reviewed_by = user
        self.review_comments = comments
        self.approved_at = None
        self.approved_by = None
        self.submitted_at = None
        self.submitted_by = None
        self.updated_by = user
        self.save()

    def publish(self, user):
        """
        Put the record on the public website, and create the public copies of
        the files that were approved with it.

        Refuses unless the content is approved and the record above it is
        already public: a project page reachable under a withdrawn programme
        is exactly the accidental disclosure this module exists to prevent.

        Returns the files released with it and the files held back for want of
        a publication authority, so the view can say so.
        """
        if self.publication_status != PublicationStatus.APPROVED:
            raise ValidationError(
                "Only approved content may be published. This record is "
                f"{self.get_publication_status_display().lower()}."
            )
        if not self.parent_is_published:
            raise ValidationError(
                f"{self.parent.title} is not published, so this record cannot "
                "appear on the public website yet."
            )

        self.publication_status = PublicationStatus.PUBLISHED
        self.published_at = timezone.now()
        self.published_by = user
        self.unpublished_at = None
        self.unpublished_by = None
        self.updated_by = user
        self.save()

        # The content goes live; each approved file goes with it only if a
        # memorandum authorises that file's release. A file without one is not
        # an error that should stop the record - the description of the work is
        # cleared and can be published - so it is held back and reported, and
        # the publisher is told which ones and why.
        # Files that came down with this record the last time it was
        # unpublished go back up with it, which is what "put the programme
        # back" has to mean if it is to be usable. Files a publisher took down
        # on their own stay down: that decision was about the file, and
        # republishing the record is not a review of it.
        released, held = [], []
        for document in self.documents.filter(
            Q(status=DocumentStatus.APPROVED)
            | Q(status=DocumentStatus.WITHDRAWN, withdrawn_with_record=True)
        ):
            if document.may_be_released:
                document.publish(user)
                released.append(document)
            else:
                held.append(document)
        return {"released": released, "held": held}

    def unpublish(self, user, cascade=True):
        """
        Take the record off the public website and destroy its public copies.

        Removing the public files rather than hiding them is the whole point:
        a withdrawn document whose file is still sitting in a served directory
        has not been withdrawn.
        """
        self.publication_status = PublicationStatus.UNPUBLISHED
        self.unpublished_at = timezone.now()
        self.unpublished_by = user
        self.updated_by = user
        self.save()

        for document in self.documents.filter(status=DocumentStatus.PUBLISHED):
            document.withdraw(user, with_record=True)

        if cascade:
            for child in self.published_children():
                child.unpublish(user)

    def archive(self, user):
        """Close the record out. Withdraws it from the public website first."""
        if self.publication_status == PublicationStatus.PUBLISHED:
            self.unpublish(user)
        self.publication_status = PublicationStatus.ARCHIVED
        self.archived_at = timezone.now()
        self.archived_by = user
        self.updated_by = user
        self.save()

    def restore(self, user):
        """Bring an archived record back as a draft. Never straight to public."""
        self.publication_status = PublicationStatus.DRAFT
        self.archived_at = None
        self.archived_by = None
        self.approved_at = None
        self.approved_by = None
        self.updated_by = user
        self.save()

    def touch_content(self, user):
        """
        Called after an encoder edits the record.

        Editing approved or published content withdraws it and sends it back
        to the queue. Anything else would let cleared wording be swapped for
        uncleared wording after the fact, which is the same disclosure
        problem by a quieter route.
        """
        if self.publication_status == PublicationStatus.PUBLISHED:
            self.unpublish(user, cascade=False)
        elif self.publication_status == PublicationStatus.APPROVED:
            self.publication_status = PublicationStatus.DRAFT
            self.approved_at = None
            self.approved_by = None
            self.save(update_fields=[
                "publication_status", "approved_at", "approved_by", "updated_at",
            ])

    def published_children(self):
        """Published records one level below this one. Overridden per level."""
        return []

    # -- presentation ---------------------------------------------------

    @property
    def public_url(self):
        raise NotImplementedError

    @property
    def status_tone(self):
        """Maps the publication lifecycle onto core/status.py's vocabulary."""
        return {
            PublicationStatus.DRAFT: "draft",
            PublicationStatus.FOR_REVIEW: "for_review",
            PublicationStatus.SCREENING: "in_progress",
            PublicationStatus.REVIEW_REQUIRED: "returned",
            PublicationStatus.APPROVED: "approved",
            PublicationStatus.PUBLISHED: "published",
            PublicationStatus.UNPUBLISHED: "inactive",
            PublicationStatus.ARCHIVED: "archived",
        }.get(self.publication_status, "neutral")


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


class Program(PPARecord):
    """A programme of the Division, answering to one Organizational Outcome."""

    level_label = "Program"
    level_key = "program"

    outcome_code = models.CharField(
        "organizational outcome",
        max_length=10,
        choices=OrganizationalOutcome.choices,
        default=OrganizationalOutcome.OO1,
        db_index=True,
    )
    reference_number = models.CharField(
        max_length=60,
        blank=True,
        help_text="Issuance or reference number, if any.",
    )
    category = models.ForeignKey(
        ProgramCategory,
        on_delete=models.PROTECT,
        related_name="programs",
        null=True,
        blank=True,
    )
    objectives = models.TextField(
        blank=True, help_text="What the programme is intended to achieve."
    )
    objectives_heading = heading_field("objectives", "objectives heading")
    projects_heading = heading_field("projects", "projects list heading")

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    lead_office = models.CharField(
        max_length=150,
        blank=True,
        default="Local Government Monitoring and Evaluation Division",
    )
    covered_lgus = models.ManyToManyField(
        "lgus.LGU",
        blank=True,
        related_name="programs",
        verbose_name="covered LGUs",
        help_text="Leave empty if the programme covers the whole region.",
    )

    class Meta:
        ordering = ("outcome_code", "title")
        indexes = [
            models.Index(fields=("outcome_code", "publication_status")),
            models.Index(fields=("publication_status", "-updated_at")),
        ]

    def get_absolute_url(self):
        return reverse("programs:program_detail", args=[self.pk])

    @property
    def outcome(self):
        return self.outcome_code

    @property
    def outcome_label(self):
        return OrganizationalOutcome(self.outcome_code).label

    @property
    def outcome_detail(self):
        return outcome_detail(self.outcome_code)

    @property
    def public_url(self):
        return reverse("core:public_program", args=[self.slug])

    def published_children(self):
        return list(self.projects.published())

    @property
    def year(self):
        return self.start_date.year if self.start_date else None

    @property
    def coverage_label(self):
        """
        How much of the region the programme covers.

        Prefers a `lgu_total` annotation for the same reason `document_count`
        prefers `document_total`: this appears on every card of a listing, and
        counting per card is a query per card.
        """
        count = self.__dict__.get("lgu_total")
        if count is None:
            count = self.covered_lgus.count()
        if count == 0:
            return "Region-wide"
        return f"{count} LGU{'s' if count != 1 else ''}"


class Project(PPARecord):
    """A project delivered under a programme."""

    level_label = "Project"
    level_key = "project"

    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name="projects",
        verbose_name="parent program",
    )
    sub_projects_heading = heading_field("sub_projects", "sub-projects list heading")
    activities_heading = heading_field("activities", "activities list heading")

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("title",)
        indexes = [models.Index(fields=("program", "publication_status"))]

    def get_absolute_url(self):
        return reverse("programs:project_detail", args=[self.pk])

    @property
    def parent(self):
        return self.program

    @property
    def public_url(self):
        return reverse("core:public_project", args=[self.slug])

    def published_children(self):
        return list(self.sub_projects.published()) + list(self.activities.published())


class SubProject(PPARecord):
    """A distinct component of a project, delivered in its own right."""

    level_label = "Sub-Project"
    level_key = "sub_project"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="sub_projects",
        verbose_name="parent project",
    )
    activities_heading = heading_field("activities", "activities list heading")

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "sub-project"
        ordering = ("title",)
        indexes = [models.Index(fields=("project", "publication_status"))]

    def get_absolute_url(self):
        return reverse("programs:subproject_detail", args=[self.pk])

    @property
    def parent(self):
        return self.project

    @property
    def public_url(self):
        return reverse("core:public_subproject", args=[self.slug])

    def published_children(self):
        return list(self.activities.published())


class Activity(PPARecord):
    """
    Something the Division actually did, on a date, in a place.

    Hangs off either a project or a sub-project - never both, never neither.
    The constraint is declared at the database level as well as in `clean()`
    because a half-parented activity is invisible in the tree and would go
    unnoticed for months.
    """

    level_label = "Activity"
    level_key = "activity"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="activities",
        null=True, blank=True,
    )
    sub_project = models.ForeignKey(
        SubProject, on_delete=models.CASCADE, related_name="activities",
        null=True, blank=True, verbose_name="parent sub-project",
    )

    activity_date = models.DateField(null=True, blank=True)
    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Municipality, city or venue. Never a private address.",
    )
    accomplishment = models.TextField(
        "accomplishment / remarks",
        blank=True,
        help_text="What was achieved. Written for the public.",
    )
    accomplishment_heading = heading_field(
        "accomplishment", "accomplishment heading"
    )

    class Meta:
        verbose_name_plural = "activities"
        ordering = ("-activity_date", "title")
        constraints = [
            models.CheckConstraint(
                name="programs_activity_has_exactly_one_parent",
                condition=(
                    models.Q(project__isnull=False, sub_project__isnull=True)
                    | models.Q(project__isnull=True, sub_project__isnull=False)
                ),
            )
        ]
        indexes = [models.Index(fields=("publication_status", "-activity_date"))]

    def get_absolute_url(self):
        return reverse("programs:activity_detail", args=[self.pk])

    def clean(self):
        super().clean()
        if bool(self.project_id) == bool(self.sub_project_id):
            raise ValidationError(
                "An activity belongs to either a project or a sub-project - "
                "name exactly one."
            )

    @property
    def parent(self):
        return self.sub_project or self.project

    @property
    def public_url(self):
        return reverse("core:public_activity", args=[self.slug])


# The four levels, in order, for code that has to walk all of them.
PPA_MODELS = (Program, Project, SubProject, Activity)
PPA_MODEL_BY_KEY = {model.level_key: model for model in PPA_MODELS}


# ---------------------------------------------------------------------------
# The authority to publish
# ---------------------------------------------------------------------------


def authority_path(instance, filename):
    return f"ppa/authorities/{instance.reference_slug}/{filename}"


class PublicationAuthority(TimeStampedModel):
    """
    The written authority under which a file may be released to the public -
    normally a memorandum from the Regional Director or the Division Chief.

    Publication is the irreversible act in this module. A document that has
    been on the public website has been seen, and taking it down afterwards
    does not unsee it. So releasing one may not rest on a reviewer's opinion
    recorded as a tick: the office's authority to publish is written down
    first, and every file released is cited against it.

    This mirrors `documents.DisposalAuthority`, which guards the equivalent
    irreversible act in the document register, and for the same reason - it is
    what an auditor asks to see. "Who approved this?" is answered by the
    review trail; "under what authority was it released?" is answered here.

    One memorandum normally covers many files: a memorandum authorising the
    publication of the 2026 SGLG results authorises the whole set, and making
    the office record a separate authority per file would turn a real control
    into a formality people route around.
    """

    reference = models.CharField(
        max_length=120,
        unique=True,
        help_text="e.g. LGMED Memorandum No. 2026-014, or the issuance number.",
    )
    title = models.CharField(
        "subject",
        max_length=255,
        help_text="What the memorandum authorises, in its own words.",
    )
    approved_on = models.DateField("date issued")
    approved_by = models.CharField(
        max_length=200,
        help_text="The officer or body that issued it, e.g. the Regional Director.",
    )
    scope = models.TextField(
        blank=True,
        help_text="What this authority covers, and anything it excludes.",
    )

    # The memorandum itself, kept internally: it is the evidence behind the
    # release, not a thing being released. It is never copied to the public
    # side, and nothing here publishes it.
    memorandum = models.FileField(
        "scanned memorandum",
        upload_to=authority_path,
        storage=protected_storage,
        blank=True,
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
        help_text="The signed issuance. Stored internally; never published.",
    )

    effective_from = models.DateField(
        null=True, blank=True,
        help_text="Leave empty if it takes effect on the date it was issued.",
    )
    effective_until = models.DateField(
        null=True, blank=True,
        help_text="Leave empty if it does not expire.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Clear this to withdraw the authority. Files already "
                  "published under it stay published.",
    )

    class Meta:
        verbose_name = "publication authority"
        verbose_name_plural = "publication authorities"
        ordering = ("-approved_on", "reference")
        indexes = [models.Index(fields=("is_active", "-approved_on"))]

    def __str__(self):
        return f"{self.reference} - {self.title}"

    def get_absolute_url(self):
        return reverse("programs:authority_detail", args=[self.pk])

    def clean(self):
        super().clean()
        if (
            self.effective_from
            and self.effective_until
            and self.effective_until < self.effective_from
        ):
            raise ValidationError({
                "effective_until": "The end date must not be earlier than the start."
            })

    @property
    def reference_slug(self):
        return slugify(self.reference) or "authority"

    @property
    def start_date(self):
        return self.effective_from or self.approved_on

    def is_in_force(self, on=None):
        """
        Whether this authority permits a release today.

        Checked at the moment of publication rather than only at approval: a
        memorandum that has since been withdrawn or has run out must not still
        be letting files onto the public website.
        """
        if not self.is_active:
            return False
        on = on or timezone.localdate()
        if self.start_date and on < self.start_date:
            return False
        if self.effective_until and on > self.effective_until:
            return False
        return True

    @property
    def in_force(self):
        return self.is_in_force()

    @property
    def status_label(self):
        if not self.is_active:
            return "Withdrawn"
        today = timezone.localdate()
        if self.start_date and today < self.start_date:
            return "Not yet in effect"
        if self.effective_until and today > self.effective_until:
            return "Expired"
        return "In force"

    @property
    def status_tone(self):
        return "active" if self.in_force else "inactive"

    @property
    def released_count(self):
        return self.documents.filter(status=DocumentStatus.PUBLISHED).count()


# ---------------------------------------------------------------------------
# Supporting documents
# ---------------------------------------------------------------------------


def internal_document_path(instance, filename):
    """
    Where an uploaded file is written inside the protected directory.

    Named under a random UUID rather than under the record it belongs to, so
    that even somebody who obtains the protected root cannot walk the tree by
    guessing programme names - and so two files called `report.pdf` never
    collide.
    """
    return f"ppa/internal/{instance.internal_ref}/{filename}"


def public_document_path(instance, filename):
    """Where the *approved copy* is written, inside the served media root."""
    return f"ppa/public/{instance.public_token}/{filename}"


class SupportingDocumentQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=DocumentStatus.PUBLISHED)

    def awaiting_review(self):
        return self.filter(
            status__in=(DocumentStatus.SCREENED, DocumentStatus.SCREENING)
        )

    def flagged(self):
        return self.exclude(risk_level=RiskLevel.LOW)

    def photographs(self):
        """
        The pictures among the files, in the order somebody arranged them.

        Ordering here rather than at the call site because every screen that
        shows photographs - the public gallery, the preview, the arrange page
        - has to agree about what "first" means. `display_order` is what a
        person set; `uploaded_at` breaks a tie the way the office would expect,
        which is the order the pictures arrived in; `pk` makes it total, so a
        batch uploaded in the same second does not shuffle between requests.
        """
        return self.filter(is_image=True).order_by(
            "display_order", "uploaded_at", "pk"
        )


class SupportingDocument(models.Model):
    """
    One file uploaded against a programme, project, sub-project or activity.

    The security requirement in section 15 of the module brief is implemented
    by the two file fields below, and the distance between them is deliberate:

    `file` is the document as it was uploaded. It lives in the protected root,
    which no web server maps to a URL, and is read back only through an
    authenticated view.

    `public_file` does not exist until a reviewer approves the document *and* a
    publisher publishes it, at which point the system writes a fresh copy into
    the served media root under an unguessable token. Withdrawing the document
    deletes that copy. There is no state of this model in which making the
    internal file public is a matter of changing a boolean.
    """

    # Exactly one of these four is set - see `clean()` and the check
    # constraint. Four nullable columns rather than a generic foreign key
    # because the queries this module actually runs are "everything attached
    # to this project", and a content-type join to answer that would be
    # slower and far harder to read.
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name="documents",
        null=True, blank=True,
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="documents",
        null=True, blank=True,
    )
    sub_project = models.ForeignKey(
        SubProject, on_delete=models.CASCADE, related_name="documents",
        null=True, blank=True,
    )
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="documents",
        null=True, blank=True,
    )

    title = models.CharField(
        "document title",
        max_length=200,
        help_text="What this file is. Shown publicly if the file is released.",
    )
    kind = models.CharField(
        "type of document",
        max_length=20,
        choices=DocumentKind.choices,
        default=DocumentKind.OTHER,
    )
    description = models.CharField(max_length=255, blank=True)

    internal_ref = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    file = models.FileField(
        "file",
        upload_to=internal_document_path,
        storage=protected_storage,
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
        help_text="PDF, Word, Excel, PowerPoint, JPG or PNG. Up to 25 MB.",
    )
    original_name = models.CharField(max_length=255, blank=True, editable=False)
    size_bytes = models.PositiveIntegerField(default=0, editable=False)
    content_type = models.CharField(max_length=120, blank=True, editable=False)
    is_image = models.BooleanField(default=False, editable=False, db_index=True)

    display_order = models.PositiveIntegerField(
        "position in the gallery",
        default=0,
        db_index=True,
        help_text=(
            "Where this photograph sits in the public gallery. Set when the "
            "file is uploaded and changed on the arrange page."
        ),
    )

    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    public_file = models.FileField(
        "approved public copy",
        upload_to=public_document_path,
        blank=True,
        editable=False,
        help_text="Written by the system when the document is published.",
    )

    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.UPLOADED,
        db_index=True,
    )

    # -- the authority to release it --------------------------------------

    authority = models.ForeignKey(
        PublicationAuthority,
        on_delete=models.PROTECT,
        related_name="documents",
        null=True,
        blank=True,
        verbose_name="published under",
        help_text=(
            "The memorandum authorising this file's release. Required before "
            "it can go on the public website."
        ),
    )

    # -- what the screening found ----------------------------------------

    risk_level = models.CharField(
        "screening result",
        max_length=20,
        choices=RiskLevel.choices,
        default=RiskLevel.REVIEW_REQUIRED,
        db_index=True,
        help_text=(
            "Set by the automated screening. An unscreened file is treated as "
            "needing review, never as safe."
        ),
    )
    screened_at = models.DateTimeField(null=True, blank=True)
    screening_findings = models.JSONField(
        default=list, blank=True,
        help_text="What the screening flagged, with masked evidence.",
    )
    screening_notes = models.TextField(
        blank=True,
        help_text="How the file was read, and anything the scanner could not do.",
    )
    text_extracted = models.BooleanField(
        default=False,
        help_text="Whether the scanner could read the file's text at all.",
    )

    # -- provenance -------------------------------------------------------

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    review_comments = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    # Why the file came down, reduced to the one distinction that changes what
    # happens next: did it come down with the record that carries it, or did
    # somebody take this file down on its own?
    #
    # A file that came down with its record is expected back when the record
    # goes back up - that is what unpublishing a programme for an afternoon
    # means, and restoring twenty photographs by hand afterwards is how an
    # office ends up not restoring them.
    #
    # A file taken down on its own is the opposite: a publisher looked at that
    # file and decided it should not be shown. Republishing the record must
    # not quietly undo that decision, so this file stays down until somebody
    # publishes it deliberately. Both are one confirmed click; they simply are
    # not the same click.
    withdrawn_with_record = models.BooleanField(
        default=False,
        help_text=(
            "The file came off the website because the record carrying it "
            "did, rather than being taken down on its own."
        ),
    )

    objects = SupportingDocumentQuerySet.as_manager()

    class Meta:
        verbose_name = "supporting document"
        ordering = ("-uploaded_at",)
        constraints = [
            models.CheckConstraint(
                name="programs_document_has_exactly_one_owner",
                condition=(
                    models.Q(program__isnull=False, project__isnull=True,
                             sub_project__isnull=True, activity__isnull=True)
                    | models.Q(program__isnull=True, project__isnull=False,
                               sub_project__isnull=True, activity__isnull=True)
                    | models.Q(program__isnull=True, project__isnull=True,
                               sub_project__isnull=False, activity__isnull=True)
                    | models.Q(program__isnull=True, project__isnull=True,
                               sub_project__isnull=True, activity__isnull=False)
                ),
            )
        ]
        indexes = [
            models.Index(fields=("status", "-uploaded_at")),
            models.Index(fields=("risk_level", "status")),
            # The public gallery asks for one record's pictures in order, on
            # every programme page. Worth an index of its own.
            models.Index(fields=("is_image", "display_order")),
        ]

    def __str__(self):
        return self.title or self.filename

    def get_absolute_url(self):
        return reverse("programs:document_review", args=[self.pk])

    def clean(self):
        super().clean()
        owners = [self.program_id, self.project_id, self.sub_project_id,
                  self.activity_id]
        if sum(1 for owner in owners if owner) != 1:
            raise ValidationError(
                "A document belongs to exactly one programme, project, "
                "sub-project or activity."
            )
        if self.file and getattr(self.file, "size", 0) > MAX_UPLOAD_BYTES:
            raise ValidationError({"file": "The file must be 25 MB or smaller."})

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            self.original_name = self.filename
        if self.file:
            self.is_image = self.extension in IMAGE_EXTENSIONS
            try:
                self.size_bytes = self.file.size
            except (OSError, ValueError):  # the file is gone from disk
                pass
        if self._state.adding and not self.display_order:
            self.display_order = self.next_display_order()
        super().save(*args, **kwargs)

    def next_display_order(self):
        """
        The position a newly attached file takes: last among its siblings.

        Numbered per record rather than globally, because the only thing the
        number ever answers is "where in *this* programme's gallery does the
        picture go". Falls back to 1 when the file has no owner yet, which
        only happens in a test that builds one by hand.
        """
        owner_field = self.owner_field
        if owner_field is None:
            return 1
        highest = (
            type(self).objects
            .filter(**{owner_field: getattr(self, f"{owner_field}_id")})
            .exclude(pk=self.pk)
            .aggregate(models.Max("display_order"))["display_order__max"]
        )
        return (highest or 0) + 1

    # -- the record it belongs to -----------------------------------------

    @property
    def owner(self):
        return self.program or self.project or self.sub_project or self.activity

    @property
    def owner_field(self):
        """Which of the four foreign keys this file actually occupies."""
        for name in ("program", "project", "sub_project", "activity"):
            if getattr(self, f"{name}_id"):
                return name
        return None

    @property
    def owner_label(self):
        owner = self.owner
        return f"{owner.level_label}: {owner.title}" if owner else "Unattached"

    # -- the file ---------------------------------------------------------

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""

    @property
    def extension(self):
        name = self.file.name if self.file else ""
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""

    @property
    def internal_url(self):
        """The authenticated view that streams the internal file."""
        return reverse("programs:document_download", args=[self.pk])

    @property
    def alt_text(self):
        """
        What a screen reader says in place of the picture.

        Never empty and never the uploaded filename: a gallery of
        "IMG_20250114_093311.jpg" tells a visitor who cannot see the pictures
        nothing at all, and office filenames are exactly what this module
        refuses to publish elsewhere.
        """
        if self.description:
            return f"{self.title} - {self.description}"
        owner = self.owner
        return self.title or (f"Photograph: {owner.title}" if owner else "Photograph")

    @property
    def public_url(self):
        """
        The public web address of the *approved copy*, or None.

        Returns None rather than raising when the copy does not exist, so a
        template that asks the question of an internal document gets nothing
        instead of an internal path.
        """
        if self.status != DocumentStatus.PUBLISHED or not self.public_file:
            return None
        return reverse("core:public_document_file", args=[self.public_token])

    # -- screening --------------------------------------------------------

    @property
    def is_screened(self):
        return self.screened_at is not None

    @property
    def finding_count(self):
        return len(self.screening_findings or [])

    @property
    def risk_tone(self):
        return {
            RiskLevel.LOW: "success",
            RiskLevel.REVIEW_REQUIRED: "warning",
            RiskLevel.HIGH: "danger",
        }.get(self.risk_level, "warning")

    @property
    def risk_headline(self):
        """The sentence the review screen leads with."""
        return {
            RiskLevel.LOW: "No obvious sensitive information detected.",
            RiskLevel.REVIEW_REQUIRED: "Potential sensitive information detected.",
            RiskLevel.HIGH: (
                "Potential confidential, restricted or sensitive information "
                "detected."
            ),
        }.get(self.risk_level, "This file has not been screened.")

    @property
    def may_be_released(self):
        """
        Whether everything needed to put this file on the public website is in
        place: a reviewer has cleared it, a memorandum authorises it, and the
        record carrying it is itself public.

        All three, not any of them. Approval says the content is fit to be
        seen; the authority is the office's written decision that it be seen;
        and the record being public is what there is for it to appear on. A
        publication resting on fewer than three is a publication nobody signed
        for.

        A file that was published and then taken down satisfies the first of
        the three exactly as it did before it came down - see
        RELEASABLE_STATUSES - so it is offered again rather than sent back to
        the reviewer.
        """
        if self.status not in RELEASABLE_STATUSES:
            return False
        if self.authority is None or not self.authority.is_in_force():
            return False
        # A file is never more public than the record that carries it.
        return self.owner_is_published

    @property
    def owner_is_published(self):
        owner = self.owner
        return owner is not None and owner.is_published

    @property
    def is_awaiting_release(self):
        """
        Cleared, authorised, and attached to a record that is already public -
        so the only thing left is for a publisher to put it out.

        This state exists because a programme is published once and then added
        to for months. Every photograph and report filed after it went live
        arrives here, and without a way to release one file on its own the
        office would have to unpublish and republish the whole programme -
        taking everything else down and back up - to get one picture out.

        A withdrawn file arrives here too, which is what makes republishing it
        a single confirmed click rather than a second review.
        """
        return self.status in AWAITING_RELEASE_STATUSES and self.may_be_released

    @property
    def release_blocker(self):
        """Why this file cannot be published yet, in words, or None."""
        if self.status == DocumentStatus.PUBLISHED:
            return None
        if self.status not in AWAITING_RELEASE_STATUSES:
            return "A reviewer has not yet approved it."
        if self.authority is None:
            return "No memorandum authorising its release has been recorded."
        if not self.authority.is_in_force():
            return (
                f"{self.authority.reference} is "
                f"{self.authority.status_label.lower()}, so it cannot authorise "
                "a release."
            )
        if not self.owner_is_published:
            owner = self.owner
            return (
                f"{owner.title} is not on the public website yet. The file "
                "goes out when that record is published."
                if owner else "It is not attached to a record."
            )
        return None

    @property
    def may_be_approved_directly(self):
        """
        Whether the interface offers a one-click approval.

        False for a high-risk file. The reviewer must still open it, and the
        review screen asks them to confirm in writing that they have.
        """
        return self.risk_level != RiskLevel.HIGH

    # -- transitions ------------------------------------------------------

    def approve(self, user, comments=""):
        self.status = DocumentStatus.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = user
        self.review_comments = comments
        self.save()

    def reject(self, user, comments=""):
        """Refuse the file. Any public copy is destroyed on the way."""
        if self.public_file:
            self._delete_public_copy()
        self.status = DocumentStatus.REJECTED
        self.reviewed_at = timezone.now()
        self.reviewed_by = user
        self.review_comments = comments
        self.save()

    def request_revision(self, user, comments=""):
        self.status = DocumentStatus.FOR_REVISION
        self.reviewed_at = timezone.now()
        self.reviewed_by = user
        self.review_comments = comments
        self.save()

    def publish(self, user):
        """
        Create the public copy and point the public website at it.

        Refuses anything a reviewer has not cleared. This is the only code
        path in the system that writes a PPA file into a served directory.

        A withdrawn file is cleared - it was approved, published, and then
        taken down by a publisher - so it is republished here without being
        approved again. It keeps its file, its title, its uploader, its
        reviewer, its memorandum and its place in the gallery; the only things
        that change are the status and the publication trail.
        """
        if self.status not in RELEASABLE_STATUSES:
            raise ValidationError(
                f"{self} has not been approved for publication."
            )
        # A file is never more public than the record that carries it. Checked
        # here as well as in the view so that releasing one file on its own
        # cannot become a way around an unpublished record.
        if not self.owner_is_published:
            owner = self.owner
            raise ValidationError(
                f"{self} cannot be published: "
                + (f"{owner.title} is not on the public website."
                   if owner else "it is not attached to a record.")
            )
        # The written authority, checked here rather than only in the view, so
        # that no code path anywhere reaches `create_public_copy` without one.
        if self.authority is None:
            raise ValidationError(
                f"{self} cannot be published: no memorandum authorising its "
                "release has been recorded against it."
            )
        if not self.authority.is_in_force():
            raise ValidationError(
                f"{self} cannot be published: {self.authority.reference} is "
                f"{self.authority.status_label.lower()}."
            )
        from .publishing import create_public_copy

        create_public_copy(self)
        self.status = DocumentStatus.PUBLISHED
        self.published_at = timezone.now()
        self.published_by = user
        self.withdrawn_at = None
        self.withdrawn_by = None
        self.withdrawn_with_record = False
        self.save()

    def withdraw(self, user, with_record=False):
        """
        Take the file off the public website and delete the public copy.

        The file itself is not touched. `file`, `title`, `description`,
        `kind`, `uploaded_by`, `reviewed_by`, `authority` and `display_order`
        all survive a withdrawal; what is destroyed is the *copy* in the served
        directory, which is the thing that made it public. Publishing it again
        writes a fresh copy from the same internal file.

        `with_record` says whether this is a cascade from the record coming
        down - see the field of the same name.
        """
        self._delete_public_copy()
        self.status = DocumentStatus.WITHDRAWN
        self.withdrawn_at = timezone.now()
        self.withdrawn_by = user
        self.withdrawn_with_record = with_record
        self.save()

    def _delete_public_copy(self):
        """
        Withdraw the public copy: drop the pointer first, then the bytes.

        The order matters. Nothing serves this file from disk - it is reached
        only through `core.public_document_file`, which refuses a document
        whose `public_file` is empty - so clearing the field is what actually
        takes it off the public website, and it cannot fail. Deleting the bytes
        is housekeeping that can fail: on Windows a file still held open by a
        request in flight cannot be removed.

        Doing it the other way round would mean a locked file left the document
        published and the record still reachable, which is the one outcome a
        withdrawal must never produce. This way the disclosure stops
        immediately either way, and an orphaned file is logged for an
        administrator to sweep up.
        """
        if not self.public_file:
            self.public_file = ""
            return

        name = self.public_file.name
        storage = self.public_file.storage
        self.public_file = ""

        try:
            storage.delete(name)
        except OSError:
            logging.getLogger("lgmed.programs").exception(
                "The public copy of document %s (%s) could not be deleted from "
                "storage. It is no longer reachable - nothing serves it - but "
                "the file is still on disk and should be removed by hand.",
                self.pk, name,
            )
