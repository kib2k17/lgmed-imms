"""
Supporting documents: the papers uploaded against a record, their screening,
review and approval, and the separate public copy a publisher releases.

Part of programs.models - see its package docstring.
"""

import logging
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from ..storage import protected_storage
from .authority import PublicationAuthority
from .records import Activity, Program, Project, SubProject
from .vocabulary import (
    ALLOWED_EXTENSIONS,
    AWAITING_RELEASE_STATUSES,
    DocumentKind,
    DocumentStatus,
    IMAGE_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    RELEASABLE_STATUSES,
    RiskLevel,
)


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
        from ..publishing import create_public_copy

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
