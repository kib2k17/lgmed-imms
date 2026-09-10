"""
The calendar's views.

Every one of them starts from `CalendarActivity.objects.visible_to(request.user)`.
That is not a convention, it is the enforcement: the record page, the edit form,
the delete confirmation and the CSV export all draw from the same scoped
queryset, so an activity a user may not read returns 404 whatever primary key
or query string is typed at it, and an activity they may read but not change
returns 403 rather than quietly saving.
"""

import calendar
import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.generic import TemplateView, View

from accounts.models import Section, User
from core.mixins import CanSuperviseMixin
from core.views_base import (
    ModuleCreateView,
    ModuleDeleteView,
    ModuleDetailView,
    ModuleListView,
    ModuleUpdateView,
)

from .forms import ActivityProgressForm, CalendarActivityForm, QuickActivityForm
from .models import (
    OPEN_STATUSES,
    ActivityStatus,
    ActivityType,
    CalendarActivity,
    Priority,
    Visibility,
)

# The enum members are `str` subclasses, so the ORM stores and compares them as
# the plain values; listing them here keeps the annotations below readable.
OPEN_STATUS_VALUES = list(OPEN_STATUSES)

# Which calendar is being looked at. "Whose activities are these?"
SCOPES = (
    ("mine", "My calendar"),
    ("assigned", "Assigned to me"),
    ("shared", "Shared with me"),
    ("all", "All employees"),
)
SUPERVISOR_SCOPES = ("all",)
DEFAULT_SCOPE = "mine"

# What period is being looked at. "Over what stretch of time?"
PERIODS = (
    ("month", "Month"),
    ("week", "Week"),
    ("upcoming", "Upcoming"),
    ("overdue", "Overdue"),
)
DEFAULT_PERIOD = "month"

# How far ahead "Upcoming" looks. Long enough to cover the coming weeks the
# Chief plans against, short enough that the list stays readable.
UPCOMING_DAYS = 60


def month_bounds(first):
    """The first and last dates of the month `first` starts."""
    last_day = calendar.monthrange(first.year, first.month)[1]
    return first, first.replace(day=last_day)


def week_bounds(day):
    """The Sunday-to-Saturday week containing `day`, matching the month grid."""
    start = day - datetime.timedelta(days=(day.weekday() + 1) % 7)
    return start, start + datetime.timedelta(days=6)


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class ActivityModuleMixin:
    model = CalendarActivity
    module_key = "calendar"
    module_label = "Activity"
    module_url_name = "activities:list"
    list_label = "Calendar"

    def get_visible(self):
        """Every view's starting point. See the module docstring."""
        return CalendarActivity.objects.visible_to(self.request.user).with_people()


# ---------------------------------------------------------------------------
# The calendar itself
# ---------------------------------------------------------------------------


class CalendarView(ActivityModuleMixin, ModuleListView):
    """
    The month grid, the week, and the two questions a schedule is really asked:
    what is coming, and what has slipped.

    The grid is built server side with the standard library rather than by a
    calendar component: it prints correctly, needs no JavaScript, and the same
    markup reads as a table to assistive technology. Scripting adds a preview
    dialog on top of that; without it every event is still a link to the record.
    """

    page_title = "Calendar"
    page_subtitle = "Work plan and schedule of the Division"
    module_label = "Activities"
    template_name = "dashboard/activities/calendar.html"
    search_placeholder = "Search activities, people, venues..."
    search_fields = (
        "title", "description", "location", "participants", "remarks",
        "owner__first_name", "owner__last_name",
        "assigned_to__first_name", "assigned_to__last_name",
    )
    sort_fields = ("title", "start_date", "activity_type", "priority", "status")
    default_sort = "start_date"
    create_url_name = "activities:create"
    create_label = "Add Activity"
    empty_icon = "calendar"
    paginate_by = None
    virtual_filters = ("employee",)
    date_field = "start_date"
    date_field_label = "Activity date"
    export_columns = (
        ("Activity ID", "pk"),
        ("Activity", "title"),
        ("Type", "get_activity_type_display"),
        ("Owner", "owner_label"),
        ("Assigned to", "assigned_to.get_display_name"),
        ("Division / section", "section.name"),
        ("Start date", "start_date"),
        ("End date", "end_date"),
        ("Start time", "start_time"),
        ("End time", "end_time"),
        ("Location", "location"),
        ("LGU", "lgu.name"),
        ("Participants", "participants"),
        ("Priority", "get_priority_display"),
        ("Status", "get_status_display"),
        ("Visibility", "get_visibility_display"),
        ("Remarks", "remarks"),
        ("Created", "created_at"),
        ("Last updated", "updated_at"),
    )

    # -- what is being looked at -----------------------------------------

    @property
    def scope(self):
        requested = self.request.GET.get("scope", DEFAULT_SCOPE)
        if requested not in dict(SCOPES):
            return DEFAULT_SCOPE
        # Asking for everyone's calendar is not a way of getting it. A user
        # without the monitoring capability who types scope=all is put back on
        # their own calendar rather than refused, because there is nothing
        # underhand about the request - the sidebar simply never offered it.
        if requested in SUPERVISOR_SCOPES and not self.request.user.can_supervise:
            return DEFAULT_SCOPE
        return requested

    @property
    def period(self):
        requested = self.request.GET.get("period", DEFAULT_PERIOD)
        return requested if requested in dict(PERIODS) else DEFAULT_PERIOD

    @property
    def has_date_range(self):
        """Whether the toolbar's from/to range is in use."""
        return bool(
            self.request.GET.get("from", "").strip()
            or self.request.GET.get("to", "").strip()
        )

    def get_anchor(self):
        """The date the month or week view is centred on."""
        today = timezone.localdate()
        anchor = parse_date(self.request.GET.get("date", ""))
        if anchor:
            return anchor
        try:
            year = int(self.request.GET.get("year", today.year))
            month = int(self.request.GET.get("month", today.month))
            return datetime.date(year, min(max(month, 1), 12), 1)
        except (TypeError, ValueError):
            return today

    def get_month(self):
        return self.get_anchor().replace(day=1)

    def get_selected_day(self):
        """The day whose activities are listed beside the grid, if one is open."""
        return parse_date(self.request.GET.get("day", ""))

    def day_activities(self, day):
        """
        Everything running on one day, asked of the database rather than
        sifted out of the page.

        Filtering the loaded month would be cheaper and quietly wrong: a `day`
        outside the month on screen - typed, bookmarked, or followed from a
        link somewhere else - would come back empty rather than answered. The
        search and the filters still apply; the period does not, because the
        day is the period.
        """
        queryset = self.apply_filters(
            self.apply_search(self.apply_scope(self.get_visible()))
        )
        return queryset.in_range(day, day).order_by("start_time", "title")

    # -- querying ---------------------------------------------------------

    def apply_scope(self, queryset):
        user = self.request.user
        scope = self.scope
        if scope == "mine":
            return queryset.mine(user)
        if scope == "assigned":
            return queryset.assigned_to_user(user)
        if scope == "shared":
            # What colleagues have opened up, minus the user's own work, which
            # has its own tab. "Shared with me" that is mostly mine is useless.
            return queryset.filter(
                visibility__in=(Visibility.TEAM, Visibility.ORGANIZATION)
            ).exclude(Q(owner=user) | Q(created_by=user))
        return queryset

    def apply_period(self, queryset):
        # An explicit date range *is* the period. Narrowing to September as
        # well would hand back the intersection of two answers to the same
        # question, which is usually empty and never what was meant.
        if self.has_date_range:
            return queryset
        today = timezone.localdate()
        period = self.period
        if period == "month":
            return queryset.in_range(*month_bounds(self.get_month()))
        if period == "week":
            return queryset.in_range(*week_bounds(self.get_anchor()))
        if period == "upcoming":
            return queryset.upcoming(today).filter(
                start_date__lte=today + datetime.timedelta(days=UPCOMING_DAYS)
            )
        return queryset.overdue(today)

    def get_base_queryset(self):
        return self.apply_period(self.apply_scope(self.get_visible()))

    def apply_extra_filters(self, queryset):
        """
        Filter by employee across both roles a person can hold on an activity.

        Asking "what is Maria doing next week" should not require knowing
        whether Maria owns the activity or was assigned it by the Chief.
        """
        employee = self.request.GET.get("employee", "").strip()
        if employee.isdigit():
            queryset = queryset.filter(
                Q(owner_id=employee) | Q(assigned_to_id=employee)
            )
        return queryset

    def get_paginate_by(self, queryset):
        # The grids need the whole period in one page; the two list views are
        # open-ended and are paged like every other module table.
        if self.period in ("month", "week") and not self.has_date_range:
            return None
        from administration.models import SystemSetting

        return SystemSetting.load().records_per_page

    # -- the toolbar ------------------------------------------------------

    @property
    def filter_fields(self):
        fields = [
            ("activity_type", "Type", ActivityType.choices),
            ("status", "Status", ActivityStatus.choices),
            ("priority", "Priority", Priority.choices),
        ]
        if self.request.user.can_supervise:
            fields.insert(0, ("employee", "Employee", self.employee_choices()))
            fields.insert(1, ("section", "Division / section", self.section_choices()))
        else:
            fields.append(("visibility", "Visibility", Visibility.choices))
        return tuple(fields)

    def employee_choices(self):
        return [
            (str(u.pk), u.get_display_name())
            for u in User.objects.filter(is_active=True).order_by(
                "last_name", "first_name"
            )
        ]

    def section_choices(self):
        return [
            (str(s.pk), s.name) for s in Section.objects.filter(is_active=True)
        ]

    # -- context -----------------------------------------------------------

    def build_weeks(self, first, activities, today, selected_day):
        """The month grid: six rows of seven days, each carrying its activities."""
        by_day = self.spread_over_days(activities, *month_bounds(first))
        return [
            [
                self.day_cell(day, by_day, today, selected_day, in_month=day.month == first.month)
                for day in week
            ]
            for week in calendar.Calendar(firstweekday=6).monthdatescalendar(
                first.year, first.month
            )
        ]

    def build_week(self, anchor, activities, today, selected_day):
        start, end = week_bounds(anchor)
        by_day = self.spread_over_days(activities, start, end)
        days = [start + datetime.timedelta(days=offset) for offset in range(7)]
        return [
            self.day_cell(day, by_day, today, selected_day, in_month=True)
            for day in days
        ]

    def spread_over_days(self, activities, window_start, window_end):
        """
        Map each date in the window to the activities running on it.

        A multi-day activity appears on every one of its days, which is what a
        reader of a calendar expects: a validation that runs Monday to Friday
        should not vanish from Tuesday.
        """
        by_day = {}
        for activity in activities:
            day = max(activity.start_date, window_start)
            stop = min(activity.last_date, window_end)
            while day <= stop:
                by_day.setdefault(day, []).append(activity)
                day += datetime.timedelta(days=1)
        return by_day

    def day_cell(self, day, by_day, today, selected_day, in_month):
        return {
            "date": day,
            "in_month": in_month,
            "is_today": day == today,
            "is_selected": day == selected_day,
            "is_weekend": day.weekday() >= 5,
            "activities": by_day.get(day, []),
        }

    def get_summary(self, today):
        """The figures above the calendar - each one a question, not a total."""
        visible = self.get_visible()
        user = self.request.user
        summary = {
            "mine": visible.mine(user).open().count(),
            "assigned": visible.assigned_to_user(user).open().count(),
            "upcoming": visible.mine(user)
            .upcoming(today)
            .filter(start_date__lte=today + datetime.timedelta(days=7))
            .count(),
            "overdue": visible.mine(user).overdue(today).count(),
        }
        if user.can_supervise:
            summary["office_open"] = visible.open().count()
            summary["office_overdue"] = visible.overdue(today).count()
        return summary

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        anchor = self.get_anchor()
        first = self.get_month()
        selected_day = self.get_selected_day()
        records = context["records"]

        previous_month = (first - datetime.timedelta(days=1)).replace(day=1)
        next_month = (first.replace(day=28) + datetime.timedelta(days=7)).replace(day=1)
        week_start, week_end = week_bounds(anchor)

        context.update(
            {
                "scope": self.scope,
                "scopes": [
                    {"value": value, "label": label}
                    for value, label in SCOPES
                    if value not in SUPERVISOR_SCOPES
                    or self.request.user.can_supervise
                ],
                "period": self.period,
                "periods": [
                    {"value": value, "label": label} for value, label in PERIODS
                ],
                "month": first,
                "anchor": anchor,
                "prev_month": previous_month,
                "next_month": next_month,
                "week_start": week_start,
                "week_end": week_end,
                "prev_week": week_start - datetime.timedelta(days=7),
                "next_week": week_start + datetime.timedelta(days=7),
                "weekday_names": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
                "today": today,
                "is_current_month": (first.year, first.month)
                == (today.year, today.month),
                "is_current_week": week_start <= today <= week_end,
                "selected_day": selected_day,
                "selected_activities": (
                    self.day_activities(selected_day) if selected_day else []
                ),
                "summary": self.get_summary(today),
                # Rendered once, for the dialog that any day opens. The form is
                # blank and identical for every day; scripting fills in which
                # day was clicked, so this costs one form, not thirty-five.
                "quick_form": (
                    QuickActivityForm(user=self.request.user)
                    if self.request.user.can_encode
                    else None
                ),
                # A custom range answers for itself, as a list. Drawing a month
                # grid beside it would show a September calendar with the
                # activities of the range the user actually asked for.
                "show_month_grid": self.period == "month" and not self.has_date_range,
                "show_week_strip": self.period == "week" and not self.has_date_range,
                "has_date_range": self.has_date_range,
                "can_supervise": self.request.user.can_supervise,
                "upcoming_days": UPCOMING_DAYS,
                # Carried through the toolbar so applying a filter does not
                # throw the user back to this month's own calendar.
                "hidden_params": [
                    {"name": "scope", "value": self.request.GET.get("scope", "")},
                    {"name": "period", "value": self.request.GET.get("period", "")},
                    {"name": "year", "value": self.request.GET.get("year", "")},
                    {"name": "month", "value": self.request.GET.get("month", "")},
                    {"name": "date", "value": self.request.GET.get("date", "")},
                    {"name": "day", "value": self.request.GET.get("day", "")},
                ],
            }
        )

        if context["show_month_grid"]:
            context["weeks"] = self.build_weeks(first, records, today, selected_day)
        elif context["show_week_strip"]:
            context["week_days"] = self.build_week(
                anchor, records, today, selected_day
            )
        return context


# ---------------------------------------------------------------------------
# The Chief's monitoring view
# ---------------------------------------------------------------------------


class ActivityMonitorView(CanSuperviseMixin, ActivityModuleMixin, TemplateView):
    """
    Who is doing what, when, and what has slipped.

    The Chief's question is not "show me an activity" but "show me the
    Division": a workload per employee, a workload per section, and the two
    lists worth acting on. Every figure links through to the calendar already
    filtered, because a number an officer cannot open is a number they have to
    take on trust.
    """

    template_name = "dashboard/activities/monitor.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        horizon = today + datetime.timedelta(days=UPCOMING_DAYS)
        visible = self.get_visible()

        open_counter = Count(
            "owned_activities",
            filter=Q(owned_activities__status__in=OPEN_STATUS_VALUES),
            distinct=True,
        )
        upcoming_counter = Count(
            "owned_activities",
            filter=Q(
                owned_activities__status__in=OPEN_STATUS_VALUES,
                owned_activities__start_date__gte=today,
            ),
            distinct=True,
        )
        overdue_counter = Count(
            "owned_activities",
            filter=Q(owned_activities__status__in=OPEN_STATUS_VALUES)
            & (
                Q(owned_activities__end_date__lt=today)
                | Q(
                    owned_activities__end_date__isnull=True,
                    owned_activities__start_date__lt=today,
                )
            ),
            distinct=True,
        )
        completed_counter = Count(
            "owned_activities",
            filter=Q(owned_activities__status=ActivityStatus.COMPLETED),
            distinct=True,
        )
        assigned_counter = Count(
            "assigned_activities",
            filter=Q(assigned_activities__status__in=OPEN_STATUS_VALUES),
            distinct=True,
        )

        workload = (
            User.objects.filter(is_active=True)
            .select_related("section")
            .annotate(
                open_count=open_counter,
                upcoming_count=upcoming_counter,
                overdue_count=overdue_counter,
                completed_count=completed_counter,
                assigned_count=assigned_counter,
            )
            .order_by("last_name", "first_name")
        )

        sections = (
            Section.objects.filter(is_active=True)
            .annotate(
                member_count=Count("members", distinct=True),
                open_count=Count(
                    "activities",
                    filter=Q(activities__status__in=OPEN_STATUS_VALUES),
                    distinct=True,
                ),
                overdue_count=Count(
                    "activities",
                    filter=Q(activities__status__in=OPEN_STATUS_VALUES)
                    & (
                        Q(activities__end_date__lt=today)
                        | Q(
                            activities__end_date__isnull=True,
                            activities__start_date__lt=today,
                        )
                    ),
                    distinct=True,
                ),
            )
            .order_by("name")
        )

        context.update(
            {
                "page_title": "Activity Monitoring",
                "page_subtitle": (
                    "Who is doing what, where, and what is planned for the "
                    "coming weeks"
                ),
                # Named explicitly: the Calendar item claims the whole
                # `activities` namespace, so without this the sidebar would
                # light up Calendar while the Chief is on Monitoring.
                "active_nav": "activity_monitor",
                "breadcrumbs": [
                    {"label": "Calendar", "url": reverse("activities:list")},
                    {"label": "Monitoring"},
                ],
                "today": today,
                "horizon": horizon,
                "upcoming_days": UPCOMING_DAYS,
                "totals": {
                    "all": visible.count(),
                    "open": visible.open().count(),
                    "today": visible.in_range(today, today).count(),
                    "upcoming": visible.upcoming(today)
                    .filter(start_date__lte=horizon)
                    .count(),
                    "overdue": visible.overdue(today).count(),
                    "completed": visible.filter(
                        status=ActivityStatus.COMPLETED
                    ).count(),
                    "unassigned_owner": visible.filter(owner__isnull=True).count(),
                },
                "workload": [row for row in workload if row.open_count or row.completed_count or row.assigned_count],
                "idle": [
                    row
                    for row in workload
                    if not row.open_count and not row.assigned_count
                ],
                "sections": sections,
                "today_activities": visible.in_range(today, today).order_by(
                    "start_time", "title"
                ),
                "upcoming_activities": visible.upcoming(today)
                .filter(start_date__lte=horizon)
                .order_by("start_date", "start_time")[:15],
                "overdue_activities": visible.overdue(today).order_by(
                    "start_date", "start_time"
                )[:15],
            }
        )
        return context


# ---------------------------------------------------------------------------
# One activity
# ---------------------------------------------------------------------------


class ActivityDetailView(ActivityModuleMixin, ModuleDetailView):
    template_name = "dashboard/activities/detail.html"

    def get_queryset(self):
        return CalendarActivity.objects.visible_to(self.request.user).select_related(
            "owner", "owner__section", "assigned_to", "assigned_to__section",
            "section", "lgu", "lgu__province", "created_by", "updated_by",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["page_subtitle"] = self.object.get_activity_type_display()
        context["can_edit"] = self.object.can_be_edited_by(user)
        context["can_remove"] = self.object.can_be_deleted_by(user)
        context["can_progress"] = self.object.can_be_progressed_by(user)
        if context["can_progress"]:
            context["progress_form"] = ActivityProgressForm(instance=self.object)
        return context


class ActivityFormMixin(ActivityModuleMixin):
    form_class = CalendarActivityForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ActivityCreateView(ActivityFormMixin, ModuleCreateView):
    """
    The new-activity form, reached two ways.

    Normally it is a page of its own. The calendar's day dialog posts to the
    same URL with `quick=1` and a shorter form, because a quick way in must not
    be a second way in: one view, one set of ownership rules, one save. If that
    post fails validation the full page renders with the errors on it, which is
    also what a browser without scripting gets.
    """

    def get_form_class(self):
        return QuickActivityForm if self.is_quick() else CalendarActivityForm

    def is_quick(self):
        return "quick" in self.request.POST or "quick" in self.request.GET

    def get_initial(self):
        """Opening the form from a day starts it on that day."""
        initial = super().get_initial()
        day = parse_date(self.request.GET.get("date", ""))
        if day:
            initial["start_date"] = day
        return initial

    def get_success_url(self):
        """
        Back where the activity was added from.

        Somebody who added an activity from the calendar wants the calendar
        again, on the month they were looking at - not the record page, and not
        this month. The destination is checked against this host before it is
        used: `next` arrives in a form post, and an unchecked redirect target
        is an open redirect however innocuous the form around it looks.
        """
        destination = self.request.POST.get("next", "").strip()
        if destination and url_has_allowed_host_and_scheme(
            destination,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return destination
        return super().get_success_url()

    def form_valid(self, form):
        # An employee's activity is their own. The owner field is not offered
        # to them at all, so it is set here rather than trusted from the post.
        if not form.cleaned_data.get("owner"):
            form.instance.owner = self.request.user
        return super().form_valid(form)


class ActivityUpdateView(ActivityFormMixin, ModuleUpdateView):
    def get_queryset(self):
        # Scoped to what the user may read, so an activity they cannot see is
        # a 404 here as well; the ownership check below turns "can read but
        # not change" into an honest 403.
        return CalendarActivity.objects.visible_to(self.request.user)

    def get_object(self, queryset=None):
        activity = super().get_object(queryset)
        if not activity.can_be_edited_by(self.request.user):
            raise PermissionDenied(
                "This activity belongs to another employee. Ask its owner to "
                "make the change."
            )
        return activity


class ActivityDeleteView(ActivityModuleMixin, ModuleDeleteView):
    """
    An employee may delete their own activity.

    `ModuleDeleteView` normally reserves deletion for administrators, which is
    right for a monitoring record the Division is answerable for and wrong for
    a plan an employee made for themselves. The capability check is therefore
    lifted here and replaced by the ownership check below - which is stricter,
    not looser: an administrator's blanket `can_delete` would have let them
    remove a colleague's activity, and this does not.
    """

    capability = None

    def get_queryset(self):
        return CalendarActivity.objects.visible_to(self.request.user)

    def get_object(self, queryset=None):
        activity = super().get_object(queryset)
        if not activity.can_be_deleted_by(self.request.user):
            raise PermissionDenied(
                "This activity belongs to another employee and cannot be "
                "deleted from here."
            )
        return activity


class ActivityProgressView(ActivityModuleMixin, View):
    """
    Record where an activity stands.

    A POST-only endpoint rather than a field on the main form, because the
    person entitled to use it is not always the person entitled to edit the
    record: the employee an activity was assigned to reports on the work, and
    changes nothing else about it.
    """

    def post(self, request, pk):
        activity = get_object_or_404(
            CalendarActivity.objects.visible_to(request.user), pk=pk
        )
        if not activity.can_be_progressed_by(request.user):
            raise PermissionDenied(
                "Only the owner or the assigned employee may report on this "
                "activity."
            )
        form = ActivityProgressForm(request.POST, instance=activity)
        if form.is_valid():
            form.instance.updated_by = request.user
            form.save()
            messages.success(
                request,
                f"{activity.title} is now "
                f"{activity.get_status_display().lower()}.",
            )
        else:
            messages.error(
                request, "The update could not be saved. Check the form and retry."
            )
        return redirect(activity.get_absolute_url())
