"""
Updates and Accomplishments - the Division's own record of what it did.

The organising principle of this module is stated once, here, because every
model below follows from it:

    Staff contribute the information, but the accomplishment belongs to the
    Division.

So the record this module keeps is a *week of LGMEDD*, not a week of any one
employee. `ReportingPeriod` is that week; everything else hangs off it. Several
people contribute to the same period, and what they contribute is consolidated
into one division summary - which the Chief reviews, which is presented at the
Monday convocation, and part of which is published to the public website.

A staff member is named on an entry as its focal person, so the Division knows
who to ask about it. That is documentation, not scoring: nothing in this module
counts entries per employee, ranks them, or presents an individual's figures,
and the statistics in `stats.py` deliberately have no per-person dimension.
"""

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from administration.models import SingletonModel
from core.models import TimeStampedModel

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif")
DOCUMENT_EXTENSIONS = (
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "txt",
)

# The Division reports on a Monday-to-Friday working week: staff update the
# system on Thursday, the Chief reviews, and the week is presented at the
# convocation on the following Monday.
UPDATE_WEEKDAY = 3      # Thursday, as Python counts weekdays from Monday=0
WORKING_WEEK_DAYS = 4   # Monday + 4 = Friday


def week_bounds(day=None):
    """The Monday and Friday of the working week containing `day`."""
    day = day or timezone.localdate()
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=WORKING_WEEK_DAYS)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class PeriodStatus(models.TextChoices):
    """Where a week stands on its way from contributions to publication."""

    OPEN = "OPEN", "Open for contributions"
    FOR_REVIEW = "FOR_REVIEW", "For the Chief's review"
    REVIEWED = "REVIEWED", "Reviewed"
    PUBLISHED = "PUBLISHED", "Published"


class UpdateCategory(models.TextChoices):
    """What kind of division accomplishment an entry records."""

    ACTIVITY = "ACTIVITY", "Activity"
    INCOMING = "INCOMING", "Incoming communication"
    OUTGOING = "OUTGOING", "Outgoing communication"
    TECHNICAL_ASSISTANCE = "TECHNICAL_ASSISTANCE", "Technical assistance"
    DELIVERABLE = "DELIVERABLE", "Report / deliverable"
    POPS_PLAN = "POPS_PLAN", "POPS Plan accomplishment"
    OTHER = "OTHER", "Other accomplishment"


class ActivityType(models.TextChoices):
    """
    How the Division took part.

    The first four are the distinction the convocation actually asks for -
    whether LGMEDD ran the activity or was present at someone else's - and the
    Division's statistics report each of them separately.
    """

    CONDUCTED = "CONDUCTED", "Conducted"
    FACILITATED = "FACILITATED", "Facilitated"
    PARTICIPATED = "PARTICIPATED", "Participated in"
    ATTENDED = "ATTENDED", "Attended"
    MEETING = "MEETING", "Meeting / coordination"
    TRAINING = "TRAINING", "Training / seminar"
    NOT_APPLICABLE = "NA", "Not an activity"


class UpdateStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "Completed"
    ONGOING = "ONGOING", "Ongoing"
    PENDING = "PENDING", "Pending"
    UPCOMING = "UPCOMING", "Upcoming"


class WayForwardStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ONGOING = "ONGOING", "Ongoing"
    COMPLETED = "COMPLETED", "Completed"


class AttachmentKind(models.TextChoices):
    PHOTO = "PHOTO", "Photo documentation"
    DOCUMENT = "DOCUMENT", "Supporting document"


# Entries that count as accomplishments. An upcoming activity is recorded on
# the same week - the convocation asks for it - but it has not happened yet,
# and counting it as an accomplishment would overstate the Division's work.
ACCOMPLISHED_STATUSES = (
    UpdateStatus.COMPLETED,
    UpdateStatus.ONGOING,
    UpdateStatus.PENDING,
)

COMMUNICATION_CATEGORIES = (UpdateCategory.INCOMING, UpdateCategory.OUTGOING)


# ---------------------------------------------------------------------------
# The week
# ---------------------------------------------------------------------------


class ReportingPeriodQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=PeriodStatus.PUBLISHED, is_public=True)

    def awaiting_review(self):
        return self.filter(status=PeriodStatus.FOR_REVIEW)

    def in_year(self, year):
        return self.filter(start_date__year=year)

    def completed(self, today=None):
        """Weeks that have finished. The one still running is not a result yet."""
        return self.filter(end_date__lt=today or timezone.localdate())

    def overlapping(self, start, end):
        """Weeks that fall wholly or partly inside a closed date range."""
        return self.filter(start_date__lte=end, end_date__gte=start)


class ReportingPeriod(TimeStampedModel):
    """
    One week of LGMEDD, and the container everything else is contributed into.

    A period is unique on its start date, which is what makes it a *division*
    record rather than a personal one: there is one September 7-11 for the
    whole Division, and every contributor adds to the same one.
    """

    objects = ReportingPeriodQuerySet.as_manager()

    start_date = models.DateField(
        "week beginning",
        unique=True,
        db_index=True,
        help_text="The Monday of the reporting week.",
    )
    end_date = models.DateField(
        "week ending",
        help_text="The Friday of the reporting week.",
    )
    theme = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Optional. What the week was mainly about, for the convocation "
            "slide - e.g. SGLGB assessment of the second district."
        ),
    )
    status = models.CharField(
        max_length=20,
        choices=PeriodStatus.choices,
        default=PeriodStatus.OPEN,
        db_index=True,
    )

    convocation_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "The Monday the week is presented. Left blank, this is the Monday "
            "after the reporting week."
        ),
    )
    chief_remarks = models.TextField(
        "Division Chief's remarks",
        blank=True,
        help_text="Shown on the convocation view above the accomplishments.",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
        verbose_name="reviewed by",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    is_public = models.BooleanField(
        "Publish the division summary to the public website",
        default=False,
        help_text=(
            "Publishes the entries, photographs and POPS Plan figures that "
            "are themselves marked for public release. Nothing else leaves "
            "the system."
        ),
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "reporting period"
        ordering = ("-start_date",)
        indexes = [models.Index(fields=("status", "-start_date"))]

    def __str__(self):
        return f"LGMEDD Weekly Updates & Accomplishments, {self.label}"

    def save(self, *args, **kwargs):
        if not self.convocation_date and self.end_date:
            # The Monday after the week that is being reported on.
            self.convocation_date = self.end_date + timedelta(days=3)
        super().save(*args, **kwargs)

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "The week cannot end before it begins."}
            )

    def get_absolute_url(self):
        return reverse("updates:period_detail", args=[self.pk])

    def get_convocation_url(self):
        return reverse("updates:convocation", args=[self.pk])

    # -- the week itself -------------------------------------------------

    @classmethod
    def for_date(cls, day=None):
        """The period covering the given day, or None if nobody opened one."""
        day = day or timezone.localdate()
        return cls.objects.filter(start_date__lte=day, end_date__gte=day).first()

    @classmethod
    def current(cls):
        return cls.for_date()

    @property
    def label(self):
        """September 7-11, 2026 - or the long form across a month boundary."""
        start, end = self.start_date, self.end_date
        if start.year != end.year:
            return (
                f"{start.strftime('%B')} {start.day}, {start.year} - "
                f"{end.strftime('%B')} {end.day}, {end.year}"
            )
        if start.month == end.month:
            return f"{start.strftime('%B')} {start.day}-{end.day}, {end.year}"
        return (
            f"{start.strftime('%B')} {start.day} - "
            f"{end.strftime('%B')} {end.day}, {end.year}"
        )

    @property
    def update_deadline(self):
        """The Thursday on which the Division updates the system."""
        return self.start_date + timedelta(days=UPDATE_WEEKDAY)

    @property
    def is_current(self):
        return self.start_date <= timezone.localdate() <= self.end_date

    @property
    def is_open(self):
        return self.status == PeriodStatus.OPEN

    @property
    def is_published(self):
        return self.status == PeriodStatus.PUBLISHED and self.is_public

    @property
    def update_is_due(self):
        """True from Thursday of the week until the Chief has it for review."""
        return (
            self.status == PeriodStatus.OPEN
            and timezone.localdate() >= self.update_deadline
        )

    # -- the contributions -----------------------------------------------

    @property
    def accomplishments(self):
        return self.updates.filter(status__in=ACCOMPLISHED_STATUSES)

    @property
    def major_accomplishments(self):
        """What the Chief selected for the convocation, in the Chief's order."""
        return self.updates.filter(is_major=True).order_by(
            "convocation_order", "-activity_date"
        )

    @property
    def photos(self):
        return UpdateAttachment.objects.filter(
            update__period=self, kind=AttachmentKind.PHOTO
        ).select_related("update")

    @property
    def supporting_documents(self):
        return UpdateAttachment.objects.filter(
            update__period=self, kind=AttachmentKind.DOCUMENT
        ).select_related("update")

    @property
    def upcoming(self):
        return self.updates.filter(status=UpdateStatus.UPCOMING).order_by(
            "activity_date"
        )

    @property
    def contributor_count(self):
        """
        How many people fed the week - a measure of division-wide
        participation, never broken down by name into a per-staff figure.
        """
        return (
            self.updates.exclude(created_by__isnull=True)
            .values("created_by")
            .distinct()
            .count()
        )

    @property
    def pops_compliance(self):
        """Accomplished against target across the week's POPS Plan entries."""
        totals = self.pops_updates.aggregate(
            target=Sum("target"), accomplished=Sum("accomplished")
        )
        target = totals["target"] or 0
        accomplished = totals["accomplished"] or 0
        return {
            "target": target,
            "accomplished": accomplished,
            "percent": round(accomplished * 100 / target) if target else 0,
        }

    # -- completeness ----------------------------------------------------
    #
    # "Weekly update completion" is measured against the *contents the week is
    # expected to carry*, not against a roll of staff. Measuring it per
    # employee would turn this module into the performance monitor it is
    # explicitly not, and would answer a question nobody at the convocation
    # asks. What the Chief needs to know is which parts of the Division's week
    # are still blank - which is what `missing_components` returns.

    COMPONENTS = (
        ("Activities", "has_activities"),
        ("Communications", "has_communications"),
        ("Accomplishments", "has_accomplishments"),
        ("Photo documentation", "has_photos"),
        ("POPS Plan update", "has_pops_updates"),
        ("Ways forward", "has_ways_forward"),
        ("Upcoming activities", "has_upcoming"),
    )

    @property
    def has_activities(self):
        return self.updates.filter(category=UpdateCategory.ACTIVITY).exists()

    @property
    def has_communications(self):
        return self.updates.filter(category__in=COMMUNICATION_CATEGORIES).exists()

    @property
    def has_accomplishments(self):
        return self.accomplishments.exists()

    @property
    def has_photos(self):
        return self.photos.exists()

    @property
    def has_pops_updates(self):
        return self.pops_updates.exists()

    @property
    def has_ways_forward(self):
        return self.ways_forward.exists()

    @property
    def has_upcoming(self):
        return self.upcoming.exists()

    @property
    def component_state(self):
        return [
            {"label": label, "present": bool(getattr(self, attribute))}
            for label, attribute in self.COMPONENTS
        ]

    @property
    def completion_percent(self):
        state = self.component_state
        filled = sum(1 for component in state if component["present"])
        return round(filled * 100 / len(state)) if state else 0

    @property
    def missing_components(self):
        """The parts of the week still waiting on somebody - the Chief's list."""
        return [c["label"] for c in self.component_state if not c["present"]]

    # -- review ----------------------------------------------------------

    def submit_for_review(self, user):
        self.status = PeriodStatus.FOR_REVIEW
        self.updated_by = user
        self.save()

    def mark_reviewed(self, user):
        self.status = PeriodStatus.REVIEWED
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.updated_by = user
        self.save()

    def publish(self, user):
        self.status = PeriodStatus.PUBLISHED
        self.is_public = True
        self.published_at = timezone.now()
        if not self.reviewed_by_id:
            self.reviewed_by = user
            self.reviewed_at = timezone.now()
        self.updated_by = user
        self.save()

    def reopen(self, user):
        self.status = PeriodStatus.OPEN
        self.is_public = False
        self.published_at = None
        self.updated_by = user
        self.save()


# ---------------------------------------------------------------------------
# What the Division did
# ---------------------------------------------------------------------------


class DivisionUpdateQuerySet(models.QuerySet):
    def accomplishments(self):
        return self.filter(status__in=ACCOMPLISHED_STATUSES)

    def published(self):
        """Entries a member of the public may see, on a published week."""
        return self.filter(
            is_public=True,
            period__is_public=True,
            period__status=PeriodStatus.PUBLISHED,
        )

    def major(self):
        return self.filter(is_major=True)

    def in_year(self, year):
        return self.filter(activity_date__year=year)

    def with_related(self):
        return self.select_related("period", "focal_person", "lgu", "created_by")


class DivisionUpdate(TimeStampedModel):
    """
    One item contributed to the Division's week.

    An entry belongs to the period, never to the person who encoded it: two
    officers who worked on the same activity record it once between them, and
    the Division's figures count the work rather than the reporter.
    """

    objects = DivisionUpdateQuerySet.as_manager()

    period = models.ForeignKey(
        ReportingPeriod,
        on_delete=models.CASCADE,
        related_name="updates",
        verbose_name="reporting period",
        help_text="The division week this belongs to.",
    )

    # -- what ------------------------------------------------------------

    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=25,
        choices=UpdateCategory.choices,
        default=UpdateCategory.ACTIVITY,
        db_index=True,
    )
    activity_type = models.CharField(
        max_length=15,
        choices=ActivityType.choices,
        default=ActivityType.NOT_APPLICABLE,
        db_index=True,
        help_text=(
            "How the Division took part. Leave as 'Not an activity' for "
            "communications and deliverables."
        ),
    )
    status = models.CharField(
        max_length=15,
        choices=UpdateStatus.choices,
        default=UpdateStatus.COMPLETED,
        db_index=True,
    )
    narrative = models.TextField(
        "what was accomplished",
        blank=True,
        help_text="What the Division did, and what came of it.",
    )
    remarks = models.TextField(
        blank=True,
        help_text="Follow-through, issues met, or why the work is still open.",
    )

    # -- when and where ---------------------------------------------------

    activity_date = models.DateField(
        "date",
        db_index=True,
        help_text="The date it happened, or is set to happen.",
    )
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Leave empty for a single-day item.",
    )
    location = models.CharField(max_length=255, blank=True)
    lgu = models.ForeignKey(
        "lgus.LGU",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="division_updates",
        verbose_name="LGU concerned",
    )

    # -- who to ask about it ----------------------------------------------
    #
    # Named for documentation and accountability. Nothing in this module
    # aggregates by focal person: see the module docstring.

    focal_person = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
        verbose_name="focal person",
        help_text=(
            "The staff member who can answer for this item. Recorded for "
            "documentation, not for performance measurement."
        ),
    )
    personnel_involved = models.CharField(
        "assigned personnel / contributors",
        max_length=255,
        blank=True,
        help_text="Others who took part, separated by commas.",
    )
    partner = models.CharField(
        "partner office or agency",
        max_length=255,
        blank=True,
    )

    # -- communications ---------------------------------------------------

    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Control or reference number, for communications and reports.",
    )
    counterpart = models.CharField(
        "from / to",
        max_length=255,
        blank=True,
        help_text="Who the communication was received from, or sent to.",
    )

    # -- the Chief's selections -------------------------------------------

    is_major = models.BooleanField(
        "Present at the Monday convocation",
        default=False,
        db_index=True,
        help_text="Selected by the Division Chief as a major accomplishment.",
    )
    convocation_order = models.PositiveIntegerField(
        "order at the convocation",
        default=0,
        help_text="Lowest first. Leave at zero to order by date.",
    )
    is_public = models.BooleanField(
        "Cleared for the public website",
        default=False,
        db_index=True,
        help_text=(
            "Appears publicly once the whole week is published. Leave "
            "unticked for anything internal."
        ),
    )

    class Meta:
        verbose_name = "division update"
        ordering = ("-activity_date", "-created_at")
        indexes = [
            models.Index(fields=("period", "category")),
            models.Index(fields=("period", "status")),
            models.Index(fields=("is_public", "-activity_date")),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("updates:detail", args=[self.pk])

    def clean(self):
        if self.end_date and self.activity_date and self.end_date < self.activity_date:
            raise ValidationError({"end_date": "The end date is before the start."})
        if (
            self.period_id
            and self.activity_date
            and self.status != UpdateStatus.UPCOMING
            and not (
                self.period.start_date <= self.activity_date <= self.period.end_date
            )
        ):
            # An upcoming activity is by definition after the week; anything
            # else dated outside it has almost certainly been filed on the
            # wrong week, which is worth saying before the figures are drawn.
            raise ValidationError(
                {
                    "activity_date": (
                        "This date is outside the reporting period "
                        f"({self.period.label}). Choose the week it belongs "
                        "to, or record it as an upcoming activity."
                    )
                }
            )

    # -- presentation ------------------------------------------------------

    @property
    def is_activity(self):
        return self.category == UpdateCategory.ACTIVITY

    @property
    def is_communication(self):
        return self.category in COMMUNICATION_CATEGORIES

    @property
    def is_accomplishment(self):
        return self.status in ACCOMPLISHED_STATUSES

    @property
    def focal_person_label(self):
        return (
            self.focal_person.get_display_name()
            if self.focal_person_id
            else "Not recorded"
        )

    @property
    def date_label(self):
        if self.end_date and self.end_date != self.activity_date:
            if self.end_date.month == self.activity_date.month:
                return (
                    f"{self.activity_date.strftime('%d %b')}"
                    f"-{self.end_date.day} {self.end_date.year}"
                )
            return (
                f"{self.activity_date.strftime('%d %b')} - "
                f"{self.end_date.strftime('%d %b %Y')}"
            )
        return self.activity_date.strftime("%d %b %Y")

    @property
    def photos(self):
        return self.attachments.filter(kind=AttachmentKind.PHOTO)

    @property
    def documents(self):
        return self.attachments.filter(kind=AttachmentKind.DOCUMENT)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def attachment_path(instance, filename):
    period = instance.update.period
    return f"updates/{period.start_date:%Y/%m-%d}/{filename}"


class UpdateAttachment(models.Model):
    """
    A photograph or a supporting document, filed against an entry.

    One model rather than two: a photograph and a memorandum are the same
    record - a file, a caption, and whether the public may see it - and the
    only thing that differs is which extensions are accepted and where it is
    rendered. `kind` carries that, and `clean` enforces it.
    """

    update = models.ForeignKey(
        DivisionUpdate,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    kind = models.CharField(
        max_length=10,
        choices=AttachmentKind.choices,
        default=AttachmentKind.PHOTO,
        db_index=True,
    )
    file = models.FileField(upload_to=attachment_path)
    caption = models.CharField(
        max_length=255,
        blank=True,
        help_text="What the photograph shows, or what the document is.",
    )
    is_public = models.BooleanField(
        "Cleared for the public website",
        default=False,
        help_text="Photographs of the Division at work; never internal papers.",
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "attachment"
        ordering = ("kind", "uploaded_at")

    def __str__(self):
        return self.caption or self.filename

    def clean(self):
        extensions = (
            IMAGE_EXTENSIONS
            if self.kind == AttachmentKind.PHOTO
            else DOCUMENT_EXTENSIONS
        )
        if self.file:
            FileExtensionValidator(extensions)(self.file)

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""

    @property
    def is_photo(self):
        return self.kind == AttachmentKind.PHOTO

    @property
    def alt_text(self):
        """Never an empty alt on a content image, and never a bare filename."""
        return self.caption or self.update.title


# ---------------------------------------------------------------------------
# POPS Plan, ways forward
# ---------------------------------------------------------------------------


class PopsPlanUpdate(models.Model):
    """
    The week's movement on one Peace and Order and Public Safety commitment.

    Kept as target-and-accomplished rather than a percentage typed by hand, so
    the Division's compliance figure is arithmetic anyone can check.
    """

    period = models.ForeignKey(
        ReportingPeriod,
        on_delete=models.CASCADE,
        related_name="pops_updates",
    )
    commitment = models.CharField(
        max_length=255,
        help_text="The POPS Plan commitment or indicator being reported on.",
    )
    target = models.PositiveIntegerField(
        default=0,
        help_text="What was due this period, in whatever unit the plan uses.",
    )
    accomplished = models.PositiveIntegerField(
        default=0,
        help_text="What the Division delivered against it.",
    )
    remarks = models.TextField(blank=True)
    is_public = models.BooleanField(
        "Cleared for the public website", default=False
    )

    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "POPS Plan update"
        verbose_name_plural = "POPS Plan updates"
        ordering = ("commitment",)

    def __str__(self):
        return self.commitment

    @property
    def percent(self):
        return round(self.accomplished * 100 / self.target) if self.target else 0

    @property
    def status(self):
        """Mapped onto the shared status vocabulary for the badge."""
        if not self.target:
            return "not_assessed"
        if self.accomplished >= self.target:
            return "compliant"
        if self.accomplished:
            return "partial"
        return "not_started"


class WayForward(models.Model):
    """A next step the Division committed to at the convocation."""

    period = models.ForeignKey(
        ReportingPeriod,
        on_delete=models.CASCADE,
        related_name="ways_forward",
    )
    description = models.CharField("way forward", max_length=255)
    detail = models.TextField(blank=True)
    target_date = models.DateField(
        null=True, blank=True,
        help_text="When the Division expects to have done it.",
    )
    status = models.CharField(
        max_length=15,
        choices=WayForwardStatus.choices,
        default=WayForwardStatus.PENDING,
        db_index=True,
    )
    is_public = models.BooleanField(
        "Cleared for the public website", default=False
    )

    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "way forward"
        verbose_name_plural = "ways forward"
        ordering = ("target_date", "description")

    def __str__(self):
        return self.description

    @property
    def is_open(self):
        return self.status != WayForwardStatus.COMPLETED


# ---------------------------------------------------------------------------
# What the public website is currently showing
# ---------------------------------------------------------------------------


class DisclosureWindow(models.TextChoices):
    RECENT_WEEKS = "RECENT_WEEKS", "The most recent completed weeks"
    RECENT_MONTHS = "RECENT_MONTHS", "The most recent completed months"
    DATE_RANGE = "DATE_RANGE", "A fixed range of dates"
    ALL = "ALL", "Every week the Division has published"


def month_start(day, months_back=0):
    """The first day of the month `months_back` before the one `day` is in."""
    index = day.month - 1 - months_back
    return date(day.year + index // 12, index % 12 + 1, 1)


class PublicDisclosure(SingletonModel):
    """
    Which of the Division's published weeks the public website is showing.

    Publishing a week is the Chief saying it *may* be disclosed. This is the
    Chief saying how long it stays on the public page, and the two are kept
    apart on purpose: an office that leaves every week it has ever published on
    the front page ends up with a page nobody reads and no way to answer "what
    are we showing at the moment".

    So the default is a rolling window of recent **completed** weeks - the week
    the Division is still working on is not a published fact and does not
    appear - and the Chief can pin an exact range instead when a particular
    period is what the public should be looking at.
    """

    CACHE_KEY = "updates:public-disclosure"

    window = models.CharField(
        "what the public website shows",
        max_length=20,
        choices=DisclosureWindow.choices,
        default=DisclosureWindow.RECENT_WEEKS,
        help_text=(
            "Only weeks that have been reviewed and published are ever "
            "eligible. This decides which of them are on the site now."
        ),
    )
    weeks_shown = models.PositiveSmallIntegerField(
        "number of weeks",
        default=8,
        validators=[MinValueValidator(1), MaxValueValidator(52)],
        help_text="Used when the site shows the most recent completed weeks.",
    )
    months_shown = models.PositiveSmallIntegerField(
        "number of months",
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text=(
            "Used when the site shows recent months. Counts the current month "
            "and the ones before it."
        ),
    )
    range_start = models.DateField(
        "showing from",
        null=True, blank=True,
        help_text="Used when the site shows a fixed range of dates.",
    )
    range_end = models.DateField(
        "showing until",
        null=True, blank=True,
    )
    include_current_week = models.BooleanField(
        "Also show the week that is still running",
        default=False,
        help_text=(
            "Off by default. A week the Division has not finished is a work "
            "in progress, not an accomplishment report."
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "public disclosure window"
        verbose_name_plural = "public disclosure window"

    def __str__(self):
        return self.describe()

    def get_absolute_url(self):
        return reverse("updates:disclosure")

    def clean(self):
        if self.window != DisclosureWindow.DATE_RANGE:
            return
        if not self.range_start or not self.range_end:
            raise ValidationError(
                {
                    "range_start": (
                        "A fixed range needs both a start and an end date."
                    )
                }
            )
        if self.range_end < self.range_start:
            raise ValidationError(
                {"range_end": "The range ends before it begins."}
            )

    # -- what it selects ---------------------------------------------------

    def visible_periods(self, today=None):
        """
        The published weeks the public website is showing right now.

        Every branch starts from `published()`, so no setting here can put an
        unreviewed week on the public site - the window narrows what is
        disclosed and can never widen it.
        """
        today = today or timezone.localdate()
        periods = ReportingPeriod.objects.published()
        if not self.include_current_week:
            periods = periods.completed(today)

        if self.window == DisclosureWindow.RECENT_WEEKS:
            recent = list(
                periods.order_by("-start_date").values_list("pk", flat=True)[
                    : self.weeks_shown
                ]
            )
            return periods.filter(pk__in=recent)

        if self.window == DisclosureWindow.RECENT_MONTHS:
            return periods.filter(
                end_date__gte=month_start(today, self.months_shown - 1)
            )

        if self.window == DisclosureWindow.DATE_RANGE:
            if not (self.range_start and self.range_end):
                # A half-filled range would otherwise disclose everything,
                # which is the opposite of what a range was set to do.
                return periods.none()
            return periods.overlapping(self.range_start, self.range_end)

        return periods

    def describe(self):
        """One sentence, printed on the public page and on the Chief's form."""
        if self.window == DisclosureWindow.RECENT_WEEKS:
            weeks = self.weeks_shown
            body = (
                "the most recent completed reporting week"
                if weeks == 1
                else f"the {weeks} most recent completed reporting weeks"
            )
        elif self.window == DisclosureWindow.RECENT_MONTHS:
            months = self.months_shown
            body = (
                "this month"
                if months == 1
                else f"the last {months} months"
            )
        elif self.window == DisclosureWindow.DATE_RANGE:
            if not (self.range_start and self.range_end):
                return "No date range has been set, so nothing is being shown."
            body = (
                f"the weeks between {self.range_start:%d %B %Y} and "
                f"{self.range_end:%d %B %Y}"
            )
        else:
            body = "every week the Division has published"

        if self.include_current_week:
            return f"Showing {body}, including the week still in progress."
        return f"Showing {body}."


def disclosed_periods(today=None):
    """
    The published weeks the public website is currently showing.

    One function, so the public listing, a week's own public page and the
    public statistics all answer "what are we showing" the same way. A week
    outside the window is not merely left off a list: it 404s at its own
    address, and contributes nothing to the published figures.
    """
    return PublicDisclosure.load().visible_periods(today)


def public_periods():
    """
    Published weeks, for the public website.

    Defined here beside the models rather than in the public view, so that
    "what the public may see" is answered in one place and the answer is the
    same wherever it is asked.

    Narrower than `disclosed_periods` by one condition: a week inside the
    Chief's window with nothing at all cleared has nothing to list, so it is
    left off the listing. It still counts towards the published figures,
    because the Division did the work either way.
    """
    return (
        disclosed_periods()
        .filter(
            Q(updates__is_public=True)
            | Q(pops_updates__is_public=True)
            | Q(ways_forward__is_public=True)
        )
        .distinct()
        .order_by("-start_date")
    )
