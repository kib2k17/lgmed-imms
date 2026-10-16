"""
The tree of work: the behaviour every level shares (PPARecord), and the four
levels - Program, Project, SubProject and Activity.

Part of programs.models - see its package docstring.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.models import TimeStampedModel

from .vocabulary import (
    DocumentStatus,
    OrganizationalOutcome,
    ProgramCategory,
    ProgramStatus,
    PublicationStatus,
    REVIEWABLE_STATUSES,
    RiskLevel,
    SUBMITTABLE_STATUSES,
    outcome_detail,
)


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
        max_length=255,
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
        from .. import screening

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
