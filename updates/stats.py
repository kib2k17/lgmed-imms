"""
The Division's figures.

Every function here aggregates at one level only: LGMEDD as a whole. There is
no per-employee dimension anywhere in this file, and that is deliberate - the
question the convocation asks is "what has the Division accomplished", not
"who accomplished the most". The focal person recorded on an entry is
documentation; it is never a grouping key.

Three pages ask for these figures and they ask slightly different questions -
the internal dashboard counts every week, a week page counts one, and the
public site counts only the weeks the Chief has published. That is one piece of
arithmetic over three sets of weeks, so a `Scope` is passed around rather than
a year, and the arithmetic itself is written once.

As in `analytics/metrics.py`, each chart returns the Chart.js series *and* the
same numbers as table rows, so a figure quoted in a meeting can be read off the
page without the chart.
"""

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    ACCOMPLISHED_STATUSES,
    COMMUNICATION_CATEGORIES,
    ActivityType,
    AttachmentKind,
    DivisionUpdate,
    PopsPlanUpdate,
    disclosed_periods,
    ReportingPeriod,
    UpdateAttachment,
    UpdateCategory,
    UpdateStatus,
    WayForward,
    WayForwardStatus,
)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

# How many weeks the weekly trend looks back over. A quarter of weeks is long
# enough to show a pattern and short enough to still read at a glance.
TREND_WEEKS = 13

# What counts as "coming up soon" when the upcoming figure is broken down.
UPCOMING_SOON_DAYS = 30


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class Scope:
    """
    The reporting weeks a set of figures is computed over.

    `public_only` narrows the *row-level* records - the POPS Plan commitments
    and the ways forward, which are read as a list of their own - to what the
    Chief cleared. It deliberately does not narrow the counts: a week the
    Division published did fourteen things whether or not all fourteen were
    released one by one, and understating that would misreport the office's
    own work.
    """

    def __init__(self, periods, year=None, public_only=False):
        self.periods = periods
        self.year = year
        self.public_only = public_only

    # -- construction ----------------------------------------------------

    @classmethod
    def for_year(cls, year=None):
        periods = ReportingPeriod.objects.all()
        if year is not None:
            periods = periods.filter(start_date__year=year)
        return cls(periods, year=year)

    @classmethod
    def for_period(cls, period):
        return cls(
            ReportingPeriod.objects.filter(pk=period.pk),
            year=period.start_date.year,
        )

    @classmethod
    def for_public(cls, year=None):
        """
        Only the weeks the public website is currently showing.

        Not simply "published": the Chief's disclosure window decides which of
        the published weeks are on the site at the moment, and the figures have
        to agree with the list underneath them. A week outside the window
        contributes nothing to either.
        """
        periods = disclosed_periods()
        if year is not None:
            periods = periods.filter(start_date__year=year)
        return cls(periods, year=year, public_only=True)

    def over_the_year(self):
        """The same question asked of the whole year this scope sits in."""
        periods = ReportingPeriod.objects.all()
        if self.public_only:
            periods = disclosed_periods()
        if self.year is not None:
            periods = periods.filter(start_date__year=self.year)
        return Scope(periods, year=self.year, public_only=self.public_only)

    # -- what falls inside it --------------------------------------------

    @property
    def updates(self):
        return DivisionUpdate.objects.filter(period__in=self.periods)

    @property
    def pops(self):
        queryset = PopsPlanUpdate.objects.filter(period__in=self.periods)
        return queryset.filter(is_public=True) if self.public_only else queryset

    @property
    def ways_forward(self):
        queryset = WayForward.objects.filter(period__in=self.periods)
        return queryset.filter(is_public=True) if self.public_only else queryset

    @property
    def week_count(self):
        return self.periods.count()


def resolve_scope(year=None, period=None, scope=None):
    """Accept a scope, a single week or a year, and return a scope."""
    if scope is not None:
        return scope
    if period is not None:
        return Scope.for_period(period)
    return Scope.for_year(year)


def available_years(published_only=False):
    """
    Years that hold a reporting week, newest first.

    `published_only` means the years the public website is actually showing,
    so the year selector there never offers a year that turns out to be empty.
    """
    periods = (
        disclosed_periods() if published_only else ReportingPeriod.objects.all()
    )
    years = set(periods.values_list("start_date__year", flat=True).distinct())
    years.discard(None)
    if not published_only or not years:
        years.add(timezone.localdate().year)
    return sorted(years, reverse=True)


# ---------------------------------------------------------------------------
# The figures
# ---------------------------------------------------------------------------


def division_statistics(year=None, period=None, scope=None):
    """
    Every division figure the dashboard and the convocation ask for.

    Computed in three queries rather than twenty-odd `.count()` calls: one
    aggregate over the updates, one over the POPS Plan entries, one over the
    ways forward. A page that shows twenty figures should not cost twenty
    round trips.
    """
    scope = resolve_scope(year, period, scope)
    updates = scope.updates

    def when(**lookups):
        return Count("pk", filter=Q(**lookups))

    def activity_of(kind):
        return {"category": UpdateCategory.ACTIVITY, "activity_type": kind}

    today = timezone.localdate()
    soon = today + timedelta(days=UPCOMING_SOON_DAYS)

    counts = updates.aggregate(
        total=Count("pk"),
        accomplishments=when(status__in=ACCOMPLISHED_STATUSES),
        activities=when(category=UpdateCategory.ACTIVITY),
        incoming=when(category=UpdateCategory.INCOMING),
        outgoing=when(category=UpdateCategory.OUTGOING),
        communications=when(category__in=COMMUNICATION_CATEGORIES),
        technical_assistance=when(category=UpdateCategory.TECHNICAL_ASSISTANCE),
        deliverables=when(category=UpdateCategory.DELIVERABLE),
        pops_accomplishments=when(category=UpdateCategory.POPS_PLAN),
        # Counted inside the Activities figure rather than across every
        # category, so the breakdown printed under "7 activities" adds up to
        # seven. A sub-total that does not sum to the figure above it reads
        # as a bug, whatever it technically measures.
        attended=when(**activity_of(ActivityType.ATTENDED)),
        participated=when(**activity_of(ActivityType.PARTICIPATED)),
        facilitated=when(**activity_of(ActivityType.FACILITATED)),
        conducted=when(**activity_of(ActivityType.CONDUCTED)),
        meetings=when(**activity_of(ActivityType.MEETING)),
        trainings=when(**activity_of(ActivityType.TRAINING)),
        untyped_activities=when(
            **activity_of(ActivityType.NOT_APPLICABLE)
        ),
        completed=when(status=UpdateStatus.COMPLETED),
        ongoing=when(status=UpdateStatus.ONGOING),
        pending=when(status=UpdateStatus.PENDING),
        upcoming=when(status=UpdateStatus.UPCOMING),
        # A partition of `upcoming`, so the card's breakdown sums to it. The
        # third is a data-quality signal as much as a figure: an activity
        # still marked upcoming after its date has passed needs someone to
        # say what became of it.
        upcoming_soon=when(
            status=UpdateStatus.UPCOMING,
            activity_date__gte=today,
            activity_date__lte=soon,
        ),
        upcoming_later=when(
            status=UpdateStatus.UPCOMING, activity_date__gt=soon
        ),
        upcoming_passed=when(
            status=UpdateStatus.UPCOMING, activity_date__lt=today
        ),
        major=when(is_major=True),
        published=when(is_public=True),
    )

    pops = scope.pops.aggregate(
        entries=Count("pk"),
        target=Sum("target"),
        accomplished=Sum("accomplished"),
    )
    target = pops["target"] or 0
    accomplished = pops["accomplished"] or 0

    forward = scope.ways_forward.aggregate(
        total=Count("pk"),
        open=Count("pk", filter=~Q(status=WayForwardStatus.COMPLETED)),
    )

    completion = completion_detail(scope=scope)
    next_upcoming = (
        updates.filter(
            status=UpdateStatus.UPCOMING, activity_date__gte=today
        )
        .order_by("activity_date")
        .values_list("activity_date", flat=True)
        .first()
    )

    counts.update(
        {
            "weeks": scope.week_count,
            "upcoming_next": next_upcoming,
            "completion_parts": completion["parts"],
            "photos": UpdateAttachment.objects.filter(
                update__in=updates, kind=AttachmentKind.PHOTO
            ).count(),
            "pops_entries": pops["entries"] or 0,
            "pops_target": target,
            "pops_accomplished": accomplished,
            "pops_compliance": (
                round(accomplished * 100 / target) if target else 0
            ),
            "ways_forward": forward["total"] or 0,
            "ways_forward_open": forward["open"] or 0,
            "weekly_completion": completion["percent"],
        }
    )
    counts.update(period_totals(scope=scope))
    return counts


def completion_detail(year=None, period=None, scope=None):
    """
    How completely the Division's weeks were filled in, part by part.

    The percentage is the average of each week's own completeness - see
    `ReportingPeriod.completion_percent`, which measures the *contents* of the
    week rather than a roll of who submitted. There is no per-staff submission
    rate in this system, by design.

    The parts are what make the percentage answerable. "86%" tells nobody what
    to do; "photographs filed in 0 of 2 weeks" does, and it is the same
    arithmetic read the other way round. Both come out of one pass over the
    weeks, because `component_state` is a handful of queries per week.
    """
    scope = resolve_scope(year, period, scope)
    periods = list(scope.periods)
    labels = [label for label, _attribute in ReportingPeriod.COMPONENTS]
    present = dict.fromkeys(labels, 0)
    total = 0

    for reporting_week in periods:
        for component in reporting_week.component_state:
            if component["present"]:
                present[component["label"]] += 1
        total += reporting_week.completion_percent

    return {
        "weeks": len(periods),
        "percent": round(total / len(periods)) if periods else 0,
        "parts": [
            {
                "label": label,
                "value": present[label],
                # Over one week the question is simply whether the part is
                # there; "1 of 1" is a needlessly arithmetic way to say yes.
                "display": (
                    ("Recorded" if present[label] else "Not yet")
                    if len(periods) == 1
                    else f"{present[label]} of {len(periods)}"
                ),
                "tone": (
                    "success"
                    if periods and present[label] == len(periods)
                    else "warning"
                ),
            }
            for label in labels
        ],
    }


def weekly_completion(year=None, period=None, scope=None):
    """The completeness percentage alone. See `completion_detail`."""
    return completion_detail(year, period, scope)["percent"]


def period_totals(year=None, period=None, scope=None):
    """
    This month, this quarter and the year to date.

    Always measured over the whole year the scope sits in, even when the scope
    is one week: "year to date" on a single week's page means the year, which
    is the only reading that makes it worth printing there.
    """
    scope = resolve_scope(year, period, scope).over_the_year()
    today = timezone.localdate()
    target_year = scope.year or today.year
    accomplishments = scope.updates.filter(status__in=ACCOMPLISHED_STATUSES)
    quarter = (today.month - 1) // 3 + 1
    current_year = target_year == today.year

    return {
        "month_to_date": accomplishments.filter(
            period__start_date__month=today.month
        ).count()
        if current_year
        else 0,
        "quarter_to_date": accomplishments.filter(
            period__start_date__quarter=quarter
        ).count()
        if current_year
        else 0,
        "year_to_date": accomplishments.count(),
        "quarter_label": f"Q{quarter}",
    }


def monthly_series(scope):
    """Accomplishments per calendar month, across the scope."""
    counts = [0] * 12
    rows = (
        scope.updates.filter(status__in=ACCOMPLISHED_STATUSES)
        .values_list("period__start_date__month")
        .annotate(total=Count("pk"))
    )
    for month, total in rows:
        if month:
            counts[month - 1] = total
    return counts


def quarterly_series(scope):
    months = monthly_series(scope)
    return [sum(months[i : i + 3]) for i in range(0, 12, 3)]


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def headline_cards(stats):
    """
    The five figures the convocation slide opens with, each with the
    breakdown that makes it answerable.

    A bare "14 accomplishments" invites the next question rather than
    answering it, so every card carries the parts it is made of - and the
    parts are counted from the same population as the figure above them, so
    they add up. Ordered as the Division reads them out: what was
    accomplished, how much of it was activity, how much correspondence moved,
    how complete the record is, and what is coming.
    """
    upcoming_note = (
        f"The soonest is on {stats['upcoming_next']:%d %B %Y}."
        if stats.get("upcoming_next")
        else "Nothing is scheduled ahead at the moment."
    )
    weeks = stats.get("weeks", 0)

    upcoming_parts = [
        {
            "label": f"Within {UPCOMING_SOON_DAYS} days",
            "value": stats.get("upcoming_soon", 0),
        },
        {"label": "Later than that", "value": stats.get("upcoming_later", 0)},
    ]
    if stats.get("upcoming_passed"):
        upcoming_parts.append(
            {"label": "Date already passed", "value": stats["upcoming_passed"],
             "tone": "warning"}
        )

    activity_parts = [
        {"label": "Conducted", "value": stats["conducted"]},
        {"label": "Facilitated", "value": stats["facilitated"]},
        {"label": "Participated in", "value": stats["participated"]},
        {"label": "Attended", "value": stats["attended"]},
        {"label": "Meetings and coordination", "value": stats["meetings"]},
        {"label": "Trainings and seminars", "value": stats["trainings"]},
    ]
    if stats.get("untyped_activities"):
        activity_parts.append(
            {"label": "Type not recorded", "value": stats["untyped_activities"],
             "tone": "warning"}
        )

    return [
        {
            "label": "Accomplishments",
            "value": stats["accomplishments"],
            "meta": "Completed, ongoing and pending division work",
            "icon": "check-circle",
            "tone": "success",
            "parts": [
                {"label": "Completed", "value": stats["completed"],
                 "tone": "success"},
                {"label": "Ongoing", "value": stats["ongoing"], "tone": "info"},
                {"label": "Pending", "value": stats["pending"],
                 "tone": "warning"},
            ],
            "note": "Work still to come is counted separately.",
        },
        {
            "label": "Activities",
            "value": stats["activities"],
            "meta": "Conducted, facilitated, participated in and attended",
            "icon": "calendar",
            "parts": activity_parts,
            "note": "How the Division took part, activity by activity.",
        },
        {
            "label": "Communications",
            "value": stats["communications"],
            "meta": (
                f"{stats['incoming']} incoming &middot; {stats['outgoing']} outgoing"
            ),
            "icon": "inbox",
            "parts": [
                {"label": "Incoming", "value": stats["incoming"]},
                {"label": "Outgoing", "value": stats["outgoing"]},
            ],
            "note": "Correspondence received by and sent from the Division.",
        },
        {
            "label": "Weekly update completion",
            "value": f"{stats['weekly_completion']}%",
            "meta": "Across the sections a division week is expected to carry",
            "icon": "trending-up",
            "tone": "warning" if stats["weekly_completion"] < 80 else "success",
            "parts": stats.get("completion_parts", []),
            "note": (
                "The parts a division week is expected to carry."
                if weeks == 1
                else f"Weeks carrying each part, across {weeks} reporting weeks."
            ),
        },
        {
            "label": "Upcoming activities",
            "value": stats["upcoming"],
            "meta": "Events and commitments already on the Division's plate",
            "icon": "clock",
            "parts": upcoming_parts,
            "note": upcoming_note,
        },
    ]


def breakdown_figures(stats):
    """The fuller statement of the Division's work, as compact figures."""
    return [
        {"label": "Activities conducted", "value": stats["conducted"]},
        {"label": "Activities facilitated", "value": stats["facilitated"]},
        {"label": "Activities participated in", "value": stats["participated"]},
        {"label": "Activities attended", "value": stats["attended"]},
        {"label": "Meetings and coordination", "value": stats["meetings"]},
        {"label": "Trainings and seminars", "value": stats["trainings"]},
        {"label": "Technical assistance", "value": stats["technical_assistance"]},
        {"label": "Reports and deliverables", "value": stats["deliverables"]},
        {"label": "POPS Plan accomplishments", "value": stats["pops_accomplishments"]},
        {"label": "Incoming communications", "value": stats["incoming"], "tone": "info"},
        {"label": "Outgoing communications", "value": stats["outgoing"], "tone": "info"},
        {"label": "Completed", "value": stats["completed"], "tone": "success"},
        {"label": "Ongoing", "value": stats["ongoing"], "tone": "info"},
        {"label": "Pending", "value": stats["pending"], "tone": "warning"},
        {"label": "Upcoming", "value": stats["upcoming"]},
        {"label": "Ways forward", "value": stats["ways_forward"]},
        {"label": "Month to date", "value": stats["month_to_date"]},
        {"label": f"{stats['quarter_label']} to date", "value": stats["quarter_to_date"]},
        {"label": "Year to date", "value": stats["year_to_date"]},
        {"label": "Photo documentation", "value": stats["photos"]},
    ]


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def accomplishments_by_month(scope):
    counts = monthly_series(scope)
    return {
        "id": "accomplishmentsByMonth",
        "title": "Accomplishments by Month",
        "subtitle": f"What LGMEDD accomplished across {scope.year}.",
        "span": 2,
        "has_data": any(counts),
        "data": {"labels": MONTHS, "values": counts},
        "headers": ["Month", "Accomplishments"],
        "rows": list(zip(MONTHS, counts)),
    }


def accomplishments_by_category(scope):
    updates = scope.updates.filter(status__in=ACCOMPLISHED_STATUSES)
    counts = dict(
        updates.values_list("category").annotate(total=Count("pk")).values_list(
            "category", "total"
        )
    )
    labels = [label for _value, label in UpdateCategory.choices]
    values = [counts.get(value, 0) for value, _label in UpdateCategory.choices]
    total = sum(values)

    return {
        "id": "accomplishmentsByCategory",
        "title": "Accomplishments by Category",
        "subtitle": f"Where the Division's work fell in {scope.year}.",
        "span": 1,
        "has_data": total > 0,
        "data": {"labels": labels, "values": values},
        "headers": ["Category", "Records", "Share"],
        "rows": [
            [label, value, f"{round(value * 100 / total)}%" if total else "0%"]
            for label, value in zip(labels, values)
        ],
    }


def activities_by_type(scope):
    """How the Division took part - and never who took part."""
    updates = scope.updates.filter(category=UpdateCategory.ACTIVITY).exclude(
        activity_type=ActivityType.NOT_APPLICABLE
    )
    counts = dict(
        updates.values_list("activity_type").annotate(total=Count("pk")).values_list(
            "activity_type", "total"
        )
    )
    kinds = [
        (value, label)
        for value, label in ActivityType.choices
        if value != ActivityType.NOT_APPLICABLE
    ]
    labels = [label for _value, label in kinds]
    values = [counts.get(value, 0) for value, _label in kinds]

    return {
        "id": "activitiesByType",
        "title": "Activities by Type",
        "subtitle": f"How active the Division was in {scope.year}.",
        "span": 1,
        "has_data": any(values),
        "data": {"labels": labels, "values": values},
        "headers": ["Type", "Activities"],
        "rows": list(zip(labels, values)),
    }


def work_status(scope):
    counts = dict(
        scope.updates.values_list("status").annotate(total=Count("pk")).values_list(
            "status", "total"
        )
    )
    kinds = [
        (UpdateStatus.COMPLETED, "Completed"),
        (UpdateStatus.ONGOING, "Ongoing"),
        (UpdateStatus.PENDING, "Pending"),
        (UpdateStatus.UPCOMING, "Upcoming"),
    ]
    labels = [label for _value, label in kinds]
    values = [counts.get(value, 0) for value, _label in kinds]
    total = sum(values)

    return {
        "id": "workStatus",
        "title": "Completed, Ongoing, Pending",
        "subtitle": "What is finished and what still needs attention.",
        "span": 1,
        "has_data": total > 0,
        "data": {"labels": labels, "values": values},
        "headers": ["Status", "Records", "Share"],
        "rows": [
            [label, value, f"{round(value * 100 / total)}%" if total else "0%"]
            for label, value in zip(labels, values)
        ],
    }


def communications_flow(scope):
    incoming, outgoing = [0] * 12, [0] * 12
    rows = (
        scope.updates.filter(category__in=COMMUNICATION_CATEGORIES)
        .values_list("period__start_date__month", "category")
        .annotate(total=Count("pk"))
    )
    for month, category, total in rows:
        if not month:
            continue
        if category == UpdateCategory.INCOMING:
            incoming[month - 1] = total
        else:
            outgoing[month - 1] = total

    return {
        "id": "communicationsFlow",
        "title": "Incoming and Outgoing Communications",
        "subtitle": f"Correspondence handled by the Division in {scope.year}.",
        "span": 2,
        "has_data": any(incoming) or any(outgoing),
        "data": {"labels": MONTHS, "incoming": incoming, "outgoing": outgoing},
        "headers": ["Month", "Incoming", "Outgoing", "Total"],
        "rows": [
            [month, received, sent, received + sent]
            for month, received, sent in zip(MONTHS, incoming, outgoing)
        ],
    }


def pops_compliance(scope):
    """Accomplished against target, commitment by commitment."""
    rows = list(
        scope.pops.values("commitment")
        .annotate(target=Sum("target"), accomplished=Sum("accomplished"))
        .order_by("-target", "commitment")[:10]
    )
    labels = [row["commitment"] for row in rows]
    targets = [row["target"] or 0 for row in rows]
    accomplished = [row["accomplished"] or 0 for row in rows]

    return {
        "id": "popsCompliance",
        "title": "POPS Plan Compliance",
        "subtitle": "Delivered against what the plan committed the Division to.",
        "span": 2,
        "has_data": any(targets) or any(accomplished),
        "data": {"labels": labels, "target": targets, "accomplished": accomplished},
        "headers": ["Commitment", "Target", "Accomplished", "Compliance"],
        "rows": [
            [
                label,
                target,
                done,
                f"{round(done * 100 / target)}%" if target else "&mdash;",
            ]
            for label, target, done in zip(labels, targets, accomplished)
        ],
    }


def weekly_trend(scope):
    """The last thirteen reporting weeks, newest on the right."""
    periods = list(scope.periods.order_by("-start_date")[:TREND_WEEKS])
    periods.reverse()

    labels = [p.start_date.strftime("%d %b") for p in periods]
    values = [p.accomplishments.count() for p in periods]
    completion = [p.completion_percent for p in periods]

    return {
        "id": "weeklyTrend",
        "title": "Weekly Accomplishment Trend",
        "subtitle": "Accomplishments recorded per reporting week.",
        "span": 2,
        "has_data": any(values),
        "data": {"labels": labels, "values": values, "completion": completion},
        "headers": ["Week beginning", "Accomplishments", "Update completion"],
        "rows": [
            [label, value, f"{percent}%"]
            for label, value, percent in zip(labels, values, completion)
        ],
    }


def year_to_date_trend(scope):
    """The same monthly figures, accumulated - the Division's running total."""
    months = monthly_series(scope)
    running, cumulative = 0, []
    for value in months:
        running += value
        cumulative.append(running)

    return {
        "id": "yearToDateTrend",
        "title": "Year-to-Date Accomplishment Trend",
        "subtitle": f"The Division's running total through {scope.year}.",
        "span": 1,
        "has_data": running > 0,
        "data": {"labels": MONTHS, "values": cumulative},
        "headers": ["Month", "Month", "Year to date"],
        "rows": [
            [month, value, total]
            for month, value, total in zip(MONTHS, months, cumulative)
        ],
    }


def charts(year=None, scope=None):
    """
    The eight panels, ordered so they tile.

    Four are two columns wide and four are one, and the pages that render them
    use a three-column grid - so they are returned strictly alternating wide,
    narrow, which fills four rows exactly. Grouped any other way the grid
    leaves holes in it, because a two-wide panel will not drop into the single
    column left at the end of a row.

    The order reads as a sequence too: what was accomplished and where it fell,
    what correspondence moved and how the Division took part, how the weeks
    trend and what is still open, and the POPS Plan position beside the
    running total for the year.
    """
    scope = resolve_scope(year=year, scope=scope)
    return [
        accomplishments_by_month(scope),        # wide
        accomplishments_by_category(scope),     # narrow
        communications_flow(scope),             # wide
        activities_by_type(scope),              # narrow
        weekly_trend(scope),                    # wide
        work_status(scope),                     # narrow
        pops_compliance(scope),                 # wide
        year_to_date_trend(scope),              # narrow
    ]


# ---------------------------------------------------------------------------
# Panels that are lists rather than charts
# ---------------------------------------------------------------------------


def upcoming_activities(limit=10, from_date=None, scope=None):
    """
    What the Division has committed to next.

    Drawn from every week in the scope, not only the current one: a commitment
    recorded three weeks ago is still the Division's next activity. On a public
    scope only the cleared ones are listed, because this is a list of records
    rather than a count of them.
    """
    from_date = from_date or timezone.localdate()
    queryset = (
        scope.updates if scope is not None else DivisionUpdate.objects.all()
    ).filter(status=UpdateStatus.UPCOMING, activity_date__gte=from_date)
    if scope is not None and scope.public_only:
        queryset = queryset.filter(is_public=True)
    return queryset.with_related().order_by("activity_date")[:limit]


def open_ways_forward(limit=10, scope=None):
    queryset = (
        scope.ways_forward if scope is not None else WayForward.objects.all()
    ).exclude(status=WayForwardStatus.COMPLETED)
    return queryset.select_related("period").order_by("target_date", "description")[
        :limit
    ]


def weeks_needing_attention(limit=5):
    """
    The weeks the Chief still has to do something about: open past their
    Thursday deadline, or waiting on the review.

    Internal by nature - a week nobody has finished is not a public fact - so
    this one takes no scope and is never reached from the public site.
    """
    from .models import PeriodStatus

    today = timezone.localdate()
    return ReportingPeriod.objects.filter(
        Q(status=PeriodStatus.FOR_REVIEW)
        | Q(status=PeriodStatus.OPEN, end_date__lt=today)
    ).order_by("-start_date")[:limit]
