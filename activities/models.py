"""
The Division's work calendar.

An activity is somebody's. That single fact drives this module: every record
names the employee who owns it, optionally the employee assigned to carry it
out, and a visibility level that says who else may read it. The Division Chief
monitors the whole office; nobody else sees a colleague's private plan, and no
amount of guessing at URLs or query parameters changes that, because the
scoping lives in the queryset rather than in the template.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel


class ActivityType(models.TextChoices):
    MONITORING = "MONITORING", "Monitoring / validation"
    MEETING = "MEETING", "Meeting"
    TRAINING = "TRAINING", "Training / orientation"
    DEADLINE = "DEADLINE", "Submission deadline"
    FIELDWORK = "FIELDWORK", "Field work / travel"
    OFFICE_WORK = "OFFICE_WORK", "Office work"
    LEAVE = "LEAVE", "Leave / unavailable"
    OTHER = "OTHER", "Other"


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class ActivityStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    POSTPONED = "POSTPONED", "Postponed"
    CANCELLED = "CANCELLED", "Cancelled"


# Work that is still outstanding. An activity in one of these states whose last
# day has passed is overdue; the other two are finished business.
OPEN_STATUSES = (
    ActivityStatus.PLANNED,
    ActivityStatus.IN_PROGRESS,
    ActivityStatus.POSTPONED,
)


class Visibility(models.TextChoices):
    """Who, besides the owner and the supervisors, may read the activity."""

    PRIVATE = "PRIVATE", "Private - only me and my supervisors"
    ASSIGNED = "ASSIGNED", "Assigned users - me, the assignee and supervisors"
    TEAM = "TEAM", "My department / division / section"
    ORGANIZATION = "ORGANIZATION", "Everyone in the office"


class CalendarActivityQuerySet(models.QuerySet):
    """The questions the calendar actually asks, asked once, here."""

    # -- visibility ----------------------------------------------------

    def visible_to(self, user):
        """
        The activities `user` is permitted to read.

        This is the module's security boundary. Every view - the month grid,
        the record page, the edit form, the delete confirmation and the CSV
        export - starts from this queryset, so an activity a user may not see
        is not merely hidden from them: as far as their requests are
        concerned it does not exist, and a guessed primary key returns 404.
        """
        if not user or not user.is_authenticated:
            return self.none()
        if getattr(user, "can_supervise", False):
            return self
        mine = Q(owner=user) | Q(created_by=user) | Q(assigned_to=user)
        shared = Q(visibility=Visibility.ORGANIZATION)
        if user.section_id:
            shared |= Q(visibility=Visibility.TEAM, section_id=user.section_id)
        return self.filter(mine | shared)

    def editable_by(self, user):
        """The activities `user` may change. Narrower than `visible_to`."""
        if not user or not user.is_authenticated:
            return self.none()
        if getattr(user, "can_manage_any_activity", False):
            return self
        return self.filter(Q(owner=user) | Q(created_by=user))

    # -- whose ---------------------------------------------------------

    def owned_by(self, user):
        return self.filter(Q(owner=user) | Q(owner__isnull=True, created_by=user))

    def assigned_to_user(self, user):
        return self.filter(assigned_to=user)

    def mine(self, user):
        """Everything on one employee's own plate: owned by or assigned to them."""
        return self.filter(
            Q(owner=user) | Q(owner__isnull=True, created_by=user) | Q(assigned_to=user)
        )

    def for_section(self, section):
        return self.filter(section=section)

    # -- when ----------------------------------------------------------

    def in_range(self, start, end):
        """Activities that overlap the closed date range [start, end]."""
        return self.filter(start_date__lte=end).filter(
            Q(end_date__gte=start) | Q(end_date__isnull=True, start_date__gte=start)
        )

    def upcoming(self, today=None):
        today = today or timezone.localdate()
        return self.filter(start_date__gte=today, status__in=OPEN_STATUSES)

    def overdue(self, today=None):
        """
        Past its last day and still unfinished.

        Measured against `end_date` where there is one, so a five-day
        validation is not called overdue on its second morning.
        """
        today = today or timezone.localdate()
        return self.filter(status__in=OPEN_STATUSES).filter(
            Q(end_date__lt=today) | Q(end_date__isnull=True, start_date__lt=today)
        )

    def open(self):
        return self.filter(status__in=OPEN_STATUSES)

    def with_people(self):
        return self.select_related("owner", "assigned_to", "section", "lgu")


class CalendarActivity(TimeStampedModel):
    """A scheduled activity belonging to an employee."""

    objects = CalendarActivityQuerySet.as_manager()

    # -- what ------------------------------------------------------------

    title = models.CharField(max_length=255)
    activity_type = models.CharField(
        max_length=20, choices=ActivityType.choices,
        default=ActivityType.MEETING, db_index=True,
    )
    description = models.TextField(blank=True)

    # -- whose -----------------------------------------------------------

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # Deactivated rather than deleted is how accounts normally leave this
        # system; on the rare occasion one is deleted, the Division still needs
        # the record of what was planned. An ownerless activity falls back to
        # whoever encoded it - see `is_owned_by`.
        on_delete=models.SET_NULL,
        null=True,
        related_name="owned_activities",
        verbose_name="activity owner",
        help_text="The employee whose activity this is.",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="assigned_activities",
        verbose_name="assigned to",
        help_text=(
            "The employee responsible for carrying the activity out, when "
            "that is not the owner. Leave empty if the owner does it."
        ),
    )
    section = models.ForeignKey(
        "accounts.Section",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="activities",
        verbose_name="department / division / section",
        help_text="Defaults to the owner's section.",
    )

    # -- when ------------------------------------------------------------

    start_date = models.DateField(db_index=True)
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Leave empty for a single-day activity.",
    )
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(
        null=True, blank=True,
        help_text="Leave empty if the activity has no fixed finish.",
    )

    # -- where, and how it is going --------------------------------------

    location = models.CharField(max_length=255, blank=True)
    lgu = models.ForeignKey(
        "lgus.LGU", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="activities", verbose_name="LGU concerned",
    )
    participants = models.CharField(max_length=255, blank=True)
    priority = models.CharField(
        max_length=10, choices=Priority.choices,
        default=Priority.NORMAL, db_index=True,
    )
    status = models.CharField(
        max_length=20, choices=ActivityStatus.choices,
        default=ActivityStatus.PLANNED, db_index=True,
    )
    remarks = models.TextField(
        blank=True,
        help_text="Outcome, follow-through, or why the plan changed.",
    )

    # -- who may see it ----------------------------------------------------

    visibility = models.CharField(
        max_length=20, choices=Visibility.choices,
        default=Visibility.PRIVATE, db_index=True,
        help_text=(
            "Supervisors always see the activity for monitoring. This "
            "setting decides which colleagues do."
        ),
    )
    is_published = models.BooleanField(
        "Show on the public calendar", default=False,
        help_text=(
            "Publishes the activity to the Division's public website. Only "
            "office-wide activities may be published."
        ),
    )

    class Meta:
        verbose_name_plural = "calendar activities"
        ordering = ("start_date", "start_time", "title")
        indexes = [
            models.Index(fields=["owner", "start_date"]),
            models.Index(fields=["assigned_to", "start_date"]),
            models.Index(fields=["visibility", "start_date"]),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("activities:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        # The section is the owner's unless someone said otherwise, so the
        # Chief's "by division" view is right without every employee being
        # asked to restate on every activity which unit they work in.
        if self.section_id is None and self.owner_id is not None:
            self.section_id = self.owner.section_id
        super().save(*args, **kwargs)

    # -- people ------------------------------------------------------------

    @property
    def responsible(self):
        """The employee expected to do the work: the assignee, else the owner."""
        return self.assigned_to or self.owner

    @property
    def is_delegated(self):
        """True when the activity is carried out by someone other than its owner."""
        return bool(self.assigned_to_id and self.assigned_to_id != self.owner_id)

    @property
    def owner_label(self):
        return self.owner.get_display_name() if self.owner_id else "Not recorded"

    @property
    def responsible_label(self):
        person = self.responsible
        return person.get_display_name() if person else "Not recorded"

    # -- dates -------------------------------------------------------------

    @property
    def last_date(self):
        return self.end_date or self.start_date

    @property
    def is_past(self):
        return self.last_date < timezone.localdate()

    @property
    def is_today(self):
        today = timezone.localdate()
        return self.start_date <= today <= self.last_date

    @property
    def is_overdue(self):
        return self.status in OPEN_STATUSES and self.is_past

    @property
    def schedule_state(self):
        """
        Where the activity stands against the calendar, as distinct from what
        the employee has reported. Shown beside the status, never instead of
        it: "Completed" and "was due last week" are different statements.
        """
        if self.status == ActivityStatus.COMPLETED:
            return "completed"
        if self.status == ActivityStatus.CANCELLED:
            return "cancelled"
        if self.is_overdue:
            return "overdue"
        if self.is_today:
            return "in_progress"
        return "scheduled"

    @property
    def time_label(self):
        """"8:00 AM - 12:00 PM", "8:00 AM", or "Whole day"."""
        if not self.start_time:
            return "Whole day"
        start = self.start_time.strftime("%I:%M %p").lstrip("0")
        if not self.end_time:
            return start
        return f"{start} - {self.end_time.strftime('%I:%M %p').lstrip('0')}"

    # -- permissions -------------------------------------------------------
    #
    # The querysets above are what actually protect the data. These mirror the
    # same rules for a single object, so a template can hide a button that
    # would be refused anyway, and so a view can answer 403 - "not yours" -
    # rather than 404 when a user may read a record but not change it.

    def is_owned_by(self, user):
        if not user or not user.is_authenticated:
            return False
        if self.owner_id:
            return self.owner_id == user.pk
        return self.created_by_id == user.pk

    def can_be_viewed_by(self, user):
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "can_supervise", False):
            return True
        if self.is_owned_by(user) or self.created_by_id == user.pk:
            return True
        if self.assigned_to_id == user.pk:
            return True
        if self.visibility == Visibility.ORGANIZATION:
            return True
        if self.visibility == Visibility.TEAM:
            return bool(self.section_id) and self.section_id == user.section_id
        return False

    def can_be_edited_by(self, user):
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "can_manage_any_activity", False):
            return True
        return self.is_owned_by(user) or self.created_by_id == user.pk

    def can_be_deleted_by(self, user):
        return self.can_be_edited_by(user)

    def can_be_progressed_by(self, user):
        """
        Who may report on the work: the owner, and the employee it was assigned
        to. The assignee is the one doing it, so making them ask the owner to
        record that it is done would put the record out of date by design -
        but it stops there, at the status and the remarks.
        """
        if self.can_be_edited_by(user):
            return True
        return bool(
            user and user.is_authenticated and self.assigned_to_id == user.pk
        )
