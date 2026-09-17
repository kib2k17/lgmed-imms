"""
Tests for Updates and Accomplishments.

The module's whole premise is that the accomplishment belongs to the Division
rather than to the staff member who typed it in, so several of these tests
exist specifically to hold that line: that the figures are division-wide, that
contributions from different people land on one weekly record, and that
nothing published exposes an individual's performance.
"""

import datetime
import shutil
import tempfile

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User

from .models import (
    ActivityType,
    DisclosureWindow,
    MovType,
    DivisionUpdate,
    PeriodStatus,
    PublicDisclosure,
    PopsPlanUpdate,
    ReportingPeriod,
    UpdateCategory,
    UpdateAttachment,
    UpdateStatus,
    WayForward,
    month_start,
    public_periods,
    week_bounds,
)
from .stats import charts, division_statistics, headline_cards

MONDAY = datetime.date(2026, 9, 7)
FRIDAY = datetime.date(2026, 9, 11)


def a_finished_week(weeks_back=1):
    """
    A reporting week that has certainly ended, whenever the suite is run.

    The public site shows completed weeks only, so a fixture dated in
    whichever week the tests happen to run in would pass on a Monday and fail
    on the Friday. These are computed from today instead of pinned.
    """
    return week_bounds(timezone.localdate() - datetime.timedelta(weeks=weeks_back))


LAST_MONDAY, LAST_FRIDAY = a_finished_week(1)
EARLIER_MONDAY, EARLIER_FRIDAY = a_finished_week(2)


class WeekTests(TestCase):
    """The reporting week itself."""

    def test_week_bounds_runs_monday_to_friday(self):
        monday, friday = week_bounds(datetime.date(2026, 9, 9))
        self.assertEqual(monday, MONDAY)
        self.assertEqual(friday, FRIDAY)

    def test_the_label_reads_as_the_convocation_slide_does(self):
        period = ReportingPeriod.objects.create(start_date=MONDAY, end_date=FRIDAY)
        self.assertEqual(period.label, "September 7-11, 2026")

    def test_a_week_spanning_two_months_names_both(self):
        period = ReportingPeriod.objects.create(
            start_date=datetime.date(2026, 8, 31), end_date=datetime.date(2026, 9, 4)
        )
        self.assertEqual(period.label, "August 31 - September 4, 2026")

    def test_the_update_deadline_is_thursday_and_the_convocation_is_monday(self):
        period = ReportingPeriod.objects.create(start_date=MONDAY, end_date=FRIDAY)
        self.assertEqual(period.update_deadline, datetime.date(2026, 9, 10))
        self.assertEqual(period.update_deadline.strftime("%A"), "Thursday")
        self.assertEqual(period.convocation_date, datetime.date(2026, 9, 14))
        self.assertEqual(period.convocation_date.strftime("%A"), "Monday")

    def test_a_week_cannot_end_before_it_begins(self):
        period = ReportingPeriod(start_date=FRIDAY, end_date=MONDAY)
        with self.assertRaises(ValidationError):
            period.full_clean()

    def test_only_one_week_may_carry_a_given_monday(self):
        """One September 7-11 for the whole Division, not one per employee."""
        ReportingPeriod.objects.create(start_date=MONDAY, end_date=FRIDAY)
        duplicate = ReportingPeriod(start_date=MONDAY, end_date=FRIDAY)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()


class ContributionTests(TestCase):
    """Several people, one division record."""

    @classmethod
    def setUpTestData(cls):
        cls.period = ReportingPeriod.objects.create(
            start_date=MONDAY, end_date=FRIDAY
        )
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN, first_name="Divina"
        )
        cls.officer = User.objects.create_user(
            username="officer", password="pw", role=Role.ENCODER, first_name="Ruel"
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )

    def contribute(self, user, title, **kwargs):
        kwargs.setdefault("activity_date", MONDAY)
        kwargs.setdefault("category", UpdateCategory.ACTIVITY)
        kwargs.setdefault("status", UpdateStatus.COMPLETED)
        return DivisionUpdate.objects.create(
            period=self.period, title=title, created_by=user, **kwargs
        )

    def test_contributions_from_different_staff_land_on_one_week(self):
        self.contribute(self.officer, "SGLGB orientation, Butuan City")
        self.contribute(self.chief, "Regional coordination meeting")

        self.assertEqual(self.period.updates.count(), 2)
        self.assertEqual(self.period.contributor_count, 2)

    def test_an_entry_dated_outside_the_week_is_refused(self):
        entry = DivisionUpdate(
            period=self.period,
            title="Filed on the wrong week",
            activity_date=datetime.date(2026, 10, 5),
        )
        with self.assertRaises(ValidationError) as caught:
            entry.full_clean()
        self.assertIn("activity_date", caught.exception.error_dict)

    def test_an_upcoming_activity_may_be_dated_after_the_week(self):
        """The convocation asks what is next; that is necessarily later."""
        entry = DivisionUpdate(
            period=self.period,
            title="SGLG validation, second district",
            activity_date=datetime.date(2026, 10, 5),
            status=UpdateStatus.UPCOMING,
        )
        entry.full_clean()  # does not raise

    def test_upcoming_work_is_not_counted_as_an_accomplishment(self):
        self.contribute(self.officer, "Completed technical assistance")
        self.contribute(
            self.officer,
            "Next month's validation",
            activity_date=datetime.date(2026, 10, 5),
            status=UpdateStatus.UPCOMING,
        )

        figures = division_statistics(period=self.period)
        self.assertEqual(figures["accomplishments"], 1)
        self.assertEqual(figures["upcoming"], 1)
        self.assertEqual(figures["total"], 2)


class DivisionStatisticsTests(TestCase):
    """Figures are the Division's, and are never broken down by employee."""

    @classmethod
    def setUpTestData(cls):
        cls.period = ReportingPeriod.objects.create(
            start_date=MONDAY, end_date=FRIDAY
        )
        cls.officer = User.objects.create_user(
            username="officer", password="pw", role=Role.ENCODER
        )

        def entry(title, **kwargs):
            kwargs.setdefault("activity_date", MONDAY)
            return DivisionUpdate.objects.create(
                period=cls.period, title=title, created_by=cls.officer, **kwargs
            )

        entry(
            "Conducted the SGLGB orientation",
            category=UpdateCategory.ACTIVITY,
            activity_type=ActivityType.CONDUCTED,
        )
        entry(
            "Attended the regional management conference",
            category=UpdateCategory.ACTIVITY,
            activity_type=ActivityType.ATTENDED,
        )
        entry(
            "Coordination meeting with the PDMU",
            category=UpdateCategory.ACTIVITY,
            activity_type=ActivityType.MEETING,
            status=UpdateStatus.ONGOING,
        )
        entry("Memorandum from the Regional Director", category=UpdateCategory.INCOMING)
        entry("Reply to the Office of the Mayor", category=UpdateCategory.OUTGOING)
        entry(
            "Technical assistance on the Full Disclosure Policy",
            category=UpdateCategory.TECHNICAL_ASSISTANCE,
            status=UpdateStatus.PENDING,
        )
        entry("Quarterly accomplishment report", category=UpdateCategory.DELIVERABLE)

        PopsPlanUpdate.objects.create(
            period=cls.period, commitment="POPS Plan review", target=10, accomplished=8
        )
        WayForward.objects.create(
            period=cls.period, description="Follow through on the FDP findings"
        )

    def test_every_division_figure_the_convocation_asks_for(self):
        figures = division_statistics(period=self.period)

        self.assertEqual(figures["total"], 7)
        self.assertEqual(figures["accomplishments"], 7)
        self.assertEqual(figures["activities"], 3)
        self.assertEqual(figures["incoming"], 1)
        self.assertEqual(figures["outgoing"], 1)
        self.assertEqual(figures["communications"], 2)
        self.assertEqual(figures["conducted"], 1)
        self.assertEqual(figures["attended"], 1)
        self.assertEqual(figures["meetings"], 1)
        self.assertEqual(figures["technical_assistance"], 1)
        self.assertEqual(figures["deliverables"], 1)
        self.assertEqual(figures["completed"], 5)
        self.assertEqual(figures["ongoing"], 1)
        self.assertEqual(figures["pending"], 1)
        self.assertEqual(figures["ways_forward"], 1)
        self.assertEqual(figures["pops_compliance"], 80)

    def test_the_statistics_carry_no_per_employee_dimension(self):
        """
        A guard on the module's premise rather than on its arithmetic.

        If a figure keyed by staff member ever appears here, this test is the
        thing that should have to be deliberately changed to allow it.
        """
        figures = division_statistics(period=self.period)
        forbidden = ("staff", "employee", "person", "user", "by_focal", "ranking")
        offending = [
            key for key in figures if any(word in key for word in forbidden)
        ]
        self.assertEqual(offending, [])

    def test_the_charts_tile_a_three_column_grid_without_holes(self):
        """
        The pages lay the eight panels out in three columns, and a two-wide
        panel will not drop into the single column left at the end of a row -
        so the order `charts()` returns them in decides whether the grid has
        holes in it. Four wide and four narrow, strictly alternating, fills
        four rows exactly. Cheaper to assert here than to spot on the page.
        """
        columns = 3
        used, rows = 0, 0
        for chart in charts(year=self.period.start_date.year):
            span = chart["span"]
            self.assertLessEqual(span, columns)
            used += span
            if used == columns:
                used, rows = 0, rows + 1
            self.assertLess(
                used, columns, "a row overflowed, so the spans no longer tile"
            )
        self.assertEqual(used, 0, "the last row of charts is left part empty")
        self.assertEqual(rows, 4)

    def test_each_headline_card_carries_the_breakdown_it_is_made_of(self):
        cards = headline_cards(division_statistics(period=self.period))
        by_label = {card["label"]: card for card in cards}

        self.assertEqual(
            [part["label"] for part in by_label["Accomplishments"]["parts"]],
            ["Completed", "Ongoing", "Pending"],
        )
        self.assertEqual(
            [part["label"] for part in by_label["Communications"]["parts"]],
            ["Incoming", "Outgoing"],
        )
        self.assertEqual(
            [part["label"] for part in by_label["Activities"]["parts"]],
            [
                "Conducted", "Facilitated", "Participated in", "Attended",
                "Meetings and coordination", "Trainings and seminars",
            ],
        )

    def test_every_breakdown_adds_up_to_the_figure_above_it(self):
        """
        A sub-total that does not sum to the number printed over it reads as a
        bug whatever it technically measures, so the counts are taken from the
        same population as the headline. This is the test that says so.
        """
        cards = headline_cards(division_statistics(period=self.period))
        for card in cards:
            parts = card["parts"]
            # The completion card counts weeks, not records; it is a tally of
            # which parts are present rather than a partition of a figure.
            if not parts or card["label"] == "Weekly update completion":
                continue
            with self.subTest(card=card["label"]):
                self.assertEqual(
                    sum(part["value"] for part in parts),
                    card["value"],
                    f"the {card['label']} breakdown does not sum to its figure",
                )

    def test_an_activity_type_outside_the_activity_category_is_not_counted(self):
        """
        Activity types are counted inside the Activities figure, so a
        technical-assistance entry that also carries a type does not inflate
        the breakdown past the number above it.
        """
        DivisionUpdate.objects.create(
            period=self.period,
            title="Technical assistance, conducted on site",
            category=UpdateCategory.TECHNICAL_ASSISTANCE,
            activity_type=ActivityType.CONDUCTED,
            activity_date=MONDAY,
        )
        figures = division_statistics(period=self.period)
        card = next(
            c for c in headline_cards(figures) if c["label"] == "Activities"
        )
        self.assertEqual(
            sum(part["value"] for part in card["parts"]), card["value"]
        )
        self.assertEqual(figures["technical_assistance"], 2)

    def test_the_completion_card_names_the_parts_the_week_is_missing(self):
        """"86%" tells nobody what to do; naming the missing part does."""
        card = next(
            c
            for c in headline_cards(division_statistics(period=self.period))
            if c["label"] == "Weekly update completion"
        )
        missing = [p["label"] for p in card["parts"] if p["display"] == "Not yet"]
        self.assertEqual(missing, ["Means of verification", "Upcoming activities"])

    def test_the_upcoming_card_splits_by_how_soon(self):
        DivisionUpdate.objects.create(
            period=self.period,
            title="Next week's validation",
            status=UpdateStatus.UPCOMING,
            activity_date=timezone.localdate() + datetime.timedelta(days=3),
        )
        DivisionUpdate.objects.create(
            period=self.period,
            title="A commitment months out",
            status=UpdateStatus.UPCOMING,
            activity_date=timezone.localdate() + datetime.timedelta(days=120),
        )
        card = next(
            c
            for c in headline_cards(division_statistics(period=self.period))
            if c["label"] == "Upcoming activities"
        )
        parts = {part["label"]: part["value"] for part in card["parts"]}
        self.assertEqual(parts["Within 30 days"], 1)
        self.assertEqual(parts["Later than that"], 1)
        self.assertEqual(sum(parts.values()), card["value"])

    def test_week_completion_measures_the_contents_of_the_week(self):
        """
        Four of the seven expected components are present: activities,
        communications, accomplishments and the POPS Plan update, plus ways
        forward - photographs and upcoming activities are still missing.
        """
        self.assertEqual(
            self.period.missing_components,
            ["Means of verification", "Upcoming activities"],
        )
        self.assertEqual(self.period.completion_percent, 71)


class ReviewAndPublicationTests(TestCase):
    """The Chief reviews, selects and clears; nobody else does."""

    @classmethod
    def setUpTestData(cls):
        # A week that has finished, so publishing it actually discloses it.
        cls.period = ReportingPeriod.objects.create(
            start_date=LAST_MONDAY, end_date=LAST_FRIDAY
        )
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )
        cls.entry = DivisionUpdate.objects.create(
            period=cls.period,
            title="SGLGB orientation for the first district",
            activity_date=LAST_MONDAY,
            created_by=cls.encoder,
        )
        cls.internal = DivisionUpdate.objects.create(
            period=cls.period,
            title="Internal staffing note",
            activity_date=LAST_MONDAY,
            created_by=cls.encoder,
        )

    def review_url(self):
        return reverse("updates:review", args=[self.period.pk])

    def test_the_review_page_is_refused_to_an_encoder(self):
        self.client.force_login(self.encoder)
        self.assertEqual(self.client.get(self.review_url()).status_code, 403)

    def test_the_review_page_opens_for_the_chief(self):
        self.client.force_login(self.chief)
        self.assertEqual(self.client.get(self.review_url()).status_code, 200)

    def test_the_chief_selects_what_is_presented_on_monday(self):
        self.client.force_login(self.chief)
        self.client.post(
            self.review_url(),
            {"action": "selection", "selected": [self.entry.pk]},
        )
        self.entry.refresh_from_db()
        self.internal.refresh_from_db()
        self.assertTrue(self.entry.is_major)
        self.assertEqual(self.entry.convocation_order, 1)
        self.assertFalse(self.internal.is_major)

    def test_clearance_and_selection_are_separate_decisions(self):
        """Presenting internally is not the same act as publishing."""
        self.client.force_login(self.chief)
        self.client.post(
            self.review_url(), {"action": "selection", "selected": [self.entry.pk]}
        )
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_major)
        self.assertFalse(self.entry.is_public)

    def test_a_week_cannot_be_published_with_nothing_cleared(self):
        self.client.force_login(self.chief)
        self.client.post(self.review_url(), {"action": "publish"})
        self.period.refresh_from_db()
        self.assertNotEqual(self.period.status, PeriodStatus.PUBLISHED)
        self.assertFalse(self.period.is_public)

    def test_publishing_releases_only_what_was_cleared(self):
        self.client.force_login(self.chief)
        self.client.post(
            self.review_url(), {"action": "clearance", "entries": [self.entry.pk]}
        )
        self.client.post(self.review_url(), {"action": "publish"})

        self.period.refresh_from_db()
        self.entry.refresh_from_db()
        self.internal.refresh_from_db()
        self.assertEqual(self.period.status, PeriodStatus.PUBLISHED)
        self.assertTrue(self.entry.is_public)
        self.assertFalse(self.internal.is_public)

        response = self.client.get(
            reverse("core:public_update_week", args=[self.period.pk])
        )
        self.assertContains(response, self.entry.title)
        self.assertNotContains(response, self.internal.title)

    def test_an_unpublished_week_is_not_reachable_publicly(self):
        response = self.client.get(
            reverse("core:public_update_week", args=[self.period.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_reopening_withdraws_the_week_from_the_public_website(self):
        self.client.force_login(self.chief)
        self.client.post(
            self.review_url(), {"action": "clearance", "entries": [self.entry.pk]}
        )
        self.client.post(self.review_url(), {"action": "publish"})
        self.client.post(self.review_url(), {"action": "reopen"})

        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PeriodStatus.OPEN)
        self.assertFalse(self.period.is_public)
        self.assertEqual(
            self.client.get(
                reverse("core:public_update_week", args=[self.period.pk])
            ).status_code,
            404,
        )

    def test_any_contributor_may_hand_the_week_to_the_chief(self):
        self.client.force_login(self.encoder)
        self.client.post(reverse("updates:submit", args=[self.period.pk]))
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PeriodStatus.FOR_REVIEW)



class PublicStatisticsTests(TestCase):
    """
    The statistics the office works from, published.

    The public page counts the weeks the Chief has published and nothing else,
    so the figures are never ahead of the Division's own reviewed record.
    """

    @classmethod
    def setUpTestData(cls):
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN
        )

        cls.published = ReportingPeriod.objects.create(
            start_date=LAST_MONDAY,
            end_date=LAST_FRIDAY,
            status=PeriodStatus.PUBLISHED,
            is_public=True,
        )
        DivisionUpdate.objects.create(
            period=cls.published,
            title="Conducted the SGLGB orientation",
            category=UpdateCategory.ACTIVITY,
            activity_type=ActivityType.CONDUCTED,
            activity_date=LAST_MONDAY,
            is_public=True,
        )
        DivisionUpdate.objects.create(
            period=cls.published,
            title="Internal staffing note",
            category=UpdateCategory.ACTIVITY,
            activity_date=LAST_MONDAY,
            is_public=False,
        )
        WayForward.objects.create(
            period=cls.published, description="A cleared next step", is_public=True
        )
        WayForward.objects.create(
            period=cls.published, description="An internal next step", is_public=False
        )
        PopsPlanUpdate.objects.create(
            period=cls.published, commitment="Published commitment",
            target=10, accomplished=6, is_public=True,
        )

        # A finished week that was never reviewed. Nothing of it may reach
        # the public, whatever its own entries are flagged as.
        cls.draft = ReportingPeriod.objects.create(
            start_date=EARLIER_MONDAY, end_date=EARLIER_FRIDAY
        )
        DivisionUpdate.objects.create(
            period=cls.draft,
            title="Work from an unreviewed week",
            category=UpdateCategory.ACTIVITY,
            activity_date=EARLIER_MONDAY,
            is_public=True,
        )

    def get(self, **params):
        return self.client.get(reverse("core:public_updates"), params)

    def test_the_public_page_carries_the_division_statistics(self):
        response = self.get()
        self.assertContains(response, "Division Statistics")
        self.assertContains(response, "The Division's Work in Figures")
        self.assertContains(response, "Accomplishment Statistics")

    def test_the_figures_count_only_the_weeks_the_division_published(self):
        """
        The draft week's entry is flagged public, but its week is not - so it
        counts towards nothing here. Review comes before disclosure.
        """
        stats = self.get().context["stats"]
        self.assertEqual(stats["weeks"], 1)
        self.assertEqual(stats["accomplishments"], 2)
        self.assertNotContains(self.get(), "Work from an unreviewed week")

    def test_the_counts_are_the_division_total_for_a_published_week(self):
        """
        Both entries of the published week are counted; only the cleared one
        is named. The Division did two things and published one.
        """
        response = self.get()
        self.assertEqual(response.context["stats"]["activities"], 2)
        self.assertContains(response, "Conducted the SGLGB orientation")
        self.assertNotContains(response, "Internal staffing note")

    def test_row_level_records_are_narrowed_to_what_was_cleared(self):
        response = self.get()
        self.assertContains(response, "A cleared next step")
        self.assertNotContains(response, "An internal next step")
        self.assertEqual(response.context["stats"]["ways_forward"], 1)

    def test_every_chart_carries_its_own_table_of_figures(self):
        """Section 20: the numbers are readable without the chart."""
        for chart in self.get().context["charts"]:
            with self.subTest(chart=chart["id"]):
                self.assertTrue(chart["headers"])
                for row in chart["rows"]:
                    self.assertEqual(len(row), len(chart["headers"]))

    def test_an_unknown_year_falls_back_rather_than_failing(self):
        for value in ("abc", "1999", ""):
            with self.subTest(year=value):
                response = self.get(year=value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["year"], LAST_MONDAY.year)

    def test_the_page_stands_up_with_nothing_published(self):
        ReportingPeriod.objects.update(status=PeriodStatus.OPEN, is_public=False)
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No accomplishments published at the moment")

    def test_no_staff_name_reaches_the_statistics_page(self):
        staff = User.objects.create_user(
            username="rmatanguihan", password="pw", role=Role.ENCODER,
            first_name="Rosalinda", last_name="Matanguihan",
        )
        self.published.updates.update(focal_person=staff, created_by=staff)
        body = self.get().content.decode()
        self.assertNotIn("Matanguihan", body)
        self.assertNotIn("Rosalinda", body)



class DisclosureWindowTests(TestCase):
    """
    The Chief decides how much of the published record the public site shows.

    Two rules run through every test here: the window can only ever narrow
    what publishing already allowed, and the week the Division is still
    working on is not a published fact.
    """

    @classmethod
    def setUpTestData(cls):
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )

        # Six published weeks running back from the one before this, plus the
        # week that is still running.
        cls.weeks = []
        for weeks_back in range(1, 7):
            monday, friday = a_finished_week(weeks_back)
            cls.weeks.append(cls.publish(monday, friday))

        current_monday, current_friday = week_bounds(timezone.localdate())
        cls.current = cls.publish(current_monday, current_friday)

    @classmethod
    def publish(cls, monday, friday):
        period = ReportingPeriod.objects.create(
            start_date=monday,
            end_date=friday,
            status=PeriodStatus.PUBLISHED,
            is_public=True,
        )
        DivisionUpdate.objects.create(
            period=period,
            title=f"Division work of {monday:%d %b %Y}",
            activity_date=monday,
            is_public=True,
        )
        return period

    def setUp(self):
        cache.clear()

    def window(self, **fields):
        disclosure, _ = PublicDisclosure.objects.get_or_create(pk=1)
        for name, value in fields.items():
            setattr(disclosure, name, value)
        disclosure.save()
        cache.clear()
        return disclosure

    def visible(self):
        return set(public_periods().values_list("pk", flat=True))

    # -- the week still in progress ---------------------------------------

    def test_the_week_still_running_is_not_shown_by_default(self):
        """
        Published or not, a week the Division has not finished is a work in
        progress rather than an accomplishment report.
        """
        self.assertNotIn(self.current.pk, self.visible())
        response = self.client.get(
            reverse("core:public_update_week", args=[self.current.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_the_chief_may_choose_to_show_the_running_week(self):
        self.window(window=DisclosureWindow.ALL, include_current_week=True)
        self.assertIn(self.current.pk, self.visible())

    # -- the rolling windows ------------------------------------------------

    def test_the_default_shows_the_recent_completed_weeks(self):
        self.window(window=DisclosureWindow.RECENT_WEEKS, weeks_shown=3)
        visible = self.visible()
        self.assertEqual(len(visible), 3)
        self.assertEqual(visible, {week.pk for week in self.weeks[:3]})

    def test_a_week_outside_the_window_is_not_reachable_at_its_own_address(self):
        """
        Narrowing the window is not merely a change of listing: the week's own
        public page stops answering too.
        """
        self.window(window=DisclosureWindow.RECENT_WEEKS, weeks_shown=2)
        oldest = self.weeks[-1]
        self.assertEqual(
            self.client.get(
                reverse("core:public_update_week", args=[oldest.pk])
            ).status_code,
            404,
        )

    def test_recent_months_counts_from_the_start_of_the_month(self):
        self.window(window=DisclosureWindow.RECENT_MONTHS, months_shown=1)
        cutoff = month_start(timezone.localdate())
        expected = {
            week.pk for week in self.weeks if week.end_date >= cutoff
        }
        self.assertEqual(self.visible(), expected)

    # -- a fixed range -------------------------------------------------------

    def test_the_chief_can_pin_an_exact_range(self):
        chosen = self.weeks[2]
        self.window(
            window=DisclosureWindow.DATE_RANGE,
            range_start=chosen.start_date,
            range_end=chosen.end_date,
        )
        self.assertEqual(self.visible(), {chosen.pk})

    def test_a_range_takes_the_weeks_that_fall_inside_it(self):
        first, last = self.weeks[3], self.weeks[1]
        self.window(
            window=DisclosureWindow.DATE_RANGE,
            range_start=first.start_date,
            range_end=last.end_date,
        )
        self.assertEqual(
            self.visible(), {week.pk for week in self.weeks[1:4]}
        )

    def test_a_range_missing_a_date_shows_nothing_rather_than_everything(self):
        """
        Failing open here would disclose the whole archive at the moment the
        Chief was trying to restrict it to one period.
        """
        self.window(
            window=DisclosureWindow.DATE_RANGE,
            range_start=None,
            range_end=None,
        )
        self.assertEqual(self.visible(), set())

    def test_a_range_is_refused_unless_it_is_complete_and_in_order(self):
        disclosure = PublicDisclosure.load()
        disclosure.window = DisclosureWindow.DATE_RANGE
        disclosure.range_start = self.weeks[0].start_date
        disclosure.range_end = None
        with self.assertRaises(ValidationError):
            disclosure.full_clean()

        disclosure.range_start = self.weeks[0].end_date
        disclosure.range_end = self.weeks[0].start_date
        with self.assertRaises(ValidationError):
            disclosure.full_clean()

    # -- the window narrows, never widens ------------------------------------

    def test_no_window_can_disclose_a_week_that_was_never_published(self):
        monday, friday = a_finished_week(9)
        unreviewed = ReportingPeriod.objects.create(
            start_date=monday, end_date=friday
        )
        DivisionUpdate.objects.create(
            period=unreviewed,
            title="Never reviewed",
            activity_date=monday,
            is_public=True,
        )
        for settings_ in (
            {"window": DisclosureWindow.ALL},
            {"window": DisclosureWindow.ALL, "include_current_week": True},
            {
                "window": DisclosureWindow.DATE_RANGE,
                "range_start": monday,
                "range_end": friday,
            },
        ):
            with self.subTest(**settings_):
                self.window(**settings_)
                self.assertNotIn(unreviewed.pk, self.visible())

    def test_the_public_figures_follow_the_window(self):
        """The statistics and the list agree; both stop at the window."""
        self.window(window=DisclosureWindow.RECENT_WEEKS, weeks_shown=2)
        response = self.client.get(reverse("core:public_updates"))
        self.assertEqual(response.context["stats"]["weeks"], 2)
        self.assertEqual(response.context["stats"]["accomplishments"], 2)

        self.window(window=DisclosureWindow.RECENT_WEEKS, weeks_shown=5)
        response = self.client.get(reverse("core:public_updates"))
        self.assertEqual(response.context["stats"]["weeks"], 5)
        self.assertEqual(response.context["stats"]["accomplishments"], 5)

    def test_the_public_page_says_what_it_is_showing(self):
        self.window(window=DisclosureWindow.RECENT_WEEKS, weeks_shown=4)
        response = self.client.get(reverse("core:public_updates"))
        self.assertContains(response, "4 most recent completed reporting weeks")

    # -- who may change it ---------------------------------------------------

    def test_the_control_is_refused_to_an_encoder(self):
        self.client.force_login(self.encoder)
        response = self.client.get(reverse("updates:disclosure"))
        self.assertEqual(response.status_code, 403)

    def test_the_chief_sets_the_window_from_the_control_page(self):
        self.client.force_login(self.chief)
        url = reverse("updates:disclosure")
        self.assertEqual(self.client.get(url).status_code, 200)

        response = self.client.post(
            url,
            {
                "window": DisclosureWindow.RECENT_WEEKS,
                "weeks_shown": 2,
                "months_shown": 3,
                "range_start": "",
                "range_end": "",
            },
        )
        self.assertRedirects(response, url)

        cache.clear()
        self.assertEqual(PublicDisclosure.load().weeks_shown, 2)
        self.assertEqual(len(self.visible()), 2)

    def test_an_encoder_posting_to_the_control_changes_nothing(self):
        self.window(window=DisclosureWindow.RECENT_WEEKS, weeks_shown=6)
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("updates:disclosure"),
            {"window": DisclosureWindow.ALL, "weeks_shown": 1, "months_shown": 1},
        )
        self.assertEqual(response.status_code, 403)
        cache.clear()
        self.assertEqual(PublicDisclosure.load().weeks_shown, 6)


class MeansOfVerificationTests(TestCase):
    """
    Evidence, linked to the accomplishment it supports.

    The Chief presents this record to the department, so the test that matters
    is not that a file uploads - it is that the file appears beside the claim
    it backs up, wherever that claim is shown.
    """

    @classmethod
    def setUpClass(cls):
        cls.media_root = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.period = ReportingPeriod.objects.create(
            start_date=LAST_MONDAY, end_date=LAST_FRIDAY
        )
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )
        cls.evidenced = DivisionUpdate.objects.create(
            period=cls.period,
            title="Conducted the SGLGB orientation",
            activity_date=LAST_MONDAY,
        )
        cls.bare = DivisionUpdate.objects.create(
            period=cls.period,
            title="Coordination meeting with the PDMU",
            activity_date=LAST_MONDAY,
        )

    def file_evidence(self, update, filename, mov_type=MovType.PHOTO, public=False):
        from django.core.files.uploadedfile import SimpleUploadedFile

        attachment = UpdateAttachment(
            update=update,
            mov_type=mov_type,
            caption="Participants of the orientation",
            is_public=public,
        )
        attachment.file.save(
            filename, SimpleUploadedFile(filename, b"evidence"), save=False
        )
        attachment.full_clean(exclude=["update"])
        attachment.save()
        return attachment

    # -- what the evidence is ---------------------------------------------

    def test_evidence_is_typed_so_it_is_not_all_read_out_as_a_photo(self):
        certificate = self.file_evidence(
            self.evidenced, "certificate.pdf", MovType.CERTIFICATE
        )
        self.assertEqual(certificate.get_mov_type_display(), "Certificate")
        self.assertFalse(certificate.is_image)

    def test_a_picture_of_a_certificate_is_still_a_certificate(self):
        """
        How a file displays and what it *is* are different questions, so a
        photographed certificate is filed as a certificate and still shows.
        """
        scanned = self.file_evidence(
            self.evidenced, "certificate.jpg", MovType.CERTIFICATE
        )
        self.assertEqual(scanned.mov_type, MovType.CERTIFICATE)
        self.assertTrue(scanned.is_image)
        self.assertIn(scanned, list(self.evidenced.photos))

    def test_a_photograph_must_actually_be_an_image(self):
        with self.assertRaises(ValidationError):
            self.file_evidence(self.evidenced, "minutes.docx", MovType.PHOTO)

    def test_a_document_may_be_a_file_or_a_scan_of_one(self):
        for filename in ("issuance.pdf", "issuance.jpg"):
            with self.subTest(filename=filename):
                self.file_evidence(self.evidenced, filename, MovType.DOCUMENT)

    def test_evidence_carries_alt_text_naming_what_it_is(self):
        photo = self.file_evidence(self.evidenced, "activity.jpg")
        photo.caption = ""
        self.assertIn("Photograph", photo.alt_text)
        self.assertIn(self.evidenced.title, photo.alt_text)

    # -- the link to the accomplishment -------------------------------------

    def test_an_accomplishment_knows_whether_it_can_be_backed_up(self):
        self.file_evidence(self.evidenced, "activity.jpg")
        self.assertTrue(self.evidenced.has_mov)
        self.assertEqual(self.evidenced.mov_count, 1)
        self.assertFalse(self.bare.has_mov)

    def test_the_division_figures_count_what_can_be_evidenced(self):
        self.file_evidence(self.evidenced, "activity.jpg")
        figures = division_statistics(period=self.period)
        self.assertEqual(figures["movs"], 1)
        self.assertEqual(figures["with_mov"], 1)
        self.assertEqual(figures["without_mov"], 1)
        self.assertEqual(figures["mov_coverage"], 50)

    def test_deleting_the_accomplishment_takes_its_evidence_with_it(self):
        self.file_evidence(self.bare, "activity.jpg")
        self.assertEqual(UpdateAttachment.objects.count(), 1)
        self.bare.delete()
        self.assertEqual(UpdateAttachment.objects.count(), 0)

    # -- where the Chief sees it --------------------------------------------

    def test_the_convocation_shows_the_evidence_beside_the_accomplishment(self):
        """
        The point of the whole feature: the Chief opens one page and the claim
        and its proof are on it together.
        """
        photo = self.file_evidence(self.evidenced, "activity.jpg")
        issuance = self.file_evidence(
            self.evidenced, "memorandum.pdf", MovType.DOCUMENT
        )
        self.evidenced.is_major = True
        self.evidenced.save(update_fields=["is_major"])

        self.client.force_login(self.chief)
        response = self.client.get(
            reverse("updates:convocation", args=[self.period.pk])
        )
        self.assertContains(response, "Means of verification")
        self.assertContains(response, photo.file.url)
        self.assertContains(response, issuance.file.url)

    def test_the_convocation_says_when_an_accomplishment_has_no_evidence(self):
        self.bare.is_major = True
        self.bare.save(update_fields=["is_major"])
        self.client.force_login(self.chief)
        response = self.client.get(
            reverse("updates:convocation", args=[self.period.pk])
        )
        self.assertContains(response, "No means of verification filed yet")

    def test_the_review_page_warns_before_the_chief_stands_up(self):
        self.bare.is_major = True
        self.bare.save(update_fields=["is_major"])
        self.client.force_login(self.chief)
        response = self.client.get(reverse("updates:review", args=[self.period.pk]))
        self.assertContains(response, "no means of verification")
        self.assertEqual(
            [item.pk for item in response.context["selected_without_mov"]],
            [self.bare.pk],
        )

    def test_the_week_lists_what_is_still_awaiting_evidence(self):
        self.file_evidence(self.evidenced, "activity.jpg")
        self.client.force_login(self.chief)
        response = self.client.get(
            reverse("updates:period_detail", args=[self.period.pk])
        )
        self.assertContains(response, "Awaiting a Means of Verification")
        self.assertEqual(
            [item.pk for item in response.context["without_mov"]], [self.bare.pk]
        )

    def test_selecting_an_unevidenced_accomplishment_is_warned_not_blocked(self):
        """
        An officer records the activity on the day and files the photograph
        when it reaches them. Refusing the selection until the evidence exists
        would get neither, so the Chief is told rather than stopped.
        """
        self.client.force_login(self.chief)
        self.client.post(
            reverse("updates:review", args=[self.period.pk]),
            {"action": "selection", "selected": [self.bare.pk]},
        )
        self.bare.refresh_from_db()
        self.assertTrue(self.bare.is_major)

    # -- what reaches the public ---------------------------------------------

    def test_only_evidence_cleared_one_by_one_reaches_the_public(self):
        self.file_evidence(self.evidenced, "public.jpg", public=True)
        withheld = self.file_evidence(
            self.evidenced, "internal.pdf", MovType.DOCUMENT, public=False
        )
        shown = self.file_evidence(
            self.evidenced, "issuance.pdf", MovType.DOCUMENT, public=True
        )
        self.evidenced.is_public = True
        self.evidenced.save(update_fields=["is_public"])
        self.period.publish(self.chief)

        response = self.client.get(
            reverse("core:public_update_week", args=[self.period.pk])
        )
        self.assertContains(response, shown.file.url)
        self.assertNotContains(response, withheld.file.url)


class ModulePageTests(TestCase):
    """The pages render, and the permission rules hold."""

    @classmethod
    def setUpTestData(cls):
        cls.period = ReportingPeriod.objects.create(
            start_date=MONDAY, end_date=FRIDAY
        )
        cls.entry = DivisionUpdate.objects.create(
            period=cls.period,
            title="Conducted the SGLGB orientation",
            activity_date=MONDAY,
            activity_type=ActivityType.CONDUCTED,
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )

    def test_every_page_in_the_module_renders(self):
        self.client.force_login(self.viewer)
        for name, args in [
            ("updates:dashboard", []),
            ("updates:list", []),
            ("updates:detail", [self.entry.pk]),
            ("updates:period_list", []),
            ("updates:period_detail", [self.period.pk]),
            ("updates:convocation", [self.period.pk]),
            ("updates:convocation_latest", []),
        ]:
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)

    def test_the_dashboard_requires_signing_in(self):
        response = self.client.get(reverse("updates:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_a_viewer_may_not_post_to_the_create_form(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse("updates:create"),
            {
                "period": self.period.pk,
                "title": "Encoded by someone without the role",
                "category": UpdateCategory.ACTIVITY,
                "activity_type": ActivityType.NOT_APPLICABLE,
                "status": UpdateStatus.COMPLETED,
                "activity_date": MONDAY,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.period.updates.count(), 1)

    def test_an_encoder_contributes_to_the_current_week(self):
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("updates:create"),
            {
                "period": self.period.pk,
                "title": "Facilitated the barangay assembly briefing",
                "category": UpdateCategory.ACTIVITY,
                "activity_type": ActivityType.FACILITATED,
                "status": UpdateStatus.COMPLETED,
                "activity_date": MONDAY,
                "convocation_order": 0,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = DivisionUpdate.objects.get(
            title="Facilitated the barangay assembly briefing"
        )
        self.assertEqual(created.period, self.period)
        self.assertEqual(created.created_by, self.encoder)
        # Contributed, not owned: the entry is the Division's, and the
        # contributor cannot mark their own work for the convocation.
        self.assertFalse(created.is_major)
        self.assertFalse(created.is_public)

    def test_the_dashboard_reports_division_figures(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("updates:dashboard"))
        self.assertEqual(response.context["stats"]["activities"], 1)
        self.assertContains(response, "Division Statistics")

    def test_the_csv_export_carries_the_division_figures(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("updates:dashboard"), {"export": "csv"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        body = response.content.decode("utf-8-sig")
        self.assertIn("Division statistics", body)
        self.assertIn("Accomplishments by Month", body)


class PublicSiteTests(TestCase):
    """What the public sees is the Division, never an individual."""

    @classmethod
    def setUpTestData(cls):
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="rmatanguihan",
            password="pw",
            role=Role.ENCODER,
            first_name="Rosalinda",
            last_name="Matanguihan",
        )
        cls.period = ReportingPeriod.objects.create(
            start_date=LAST_MONDAY,
            end_date=LAST_FRIDAY,
            status=PeriodStatus.PUBLISHED,
            is_public=True,
        )
        DivisionUpdate.objects.create(
            period=cls.period,
            title="Conducted the SGLGB orientation",
            activity_date=LAST_MONDAY,
            focal_person=cls.staff,
            created_by=cls.staff,
            is_public=True,
        )

    def test_the_published_week_is_listed_publicly(self):
        response = self.client.get(reverse("core:public_updates"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.period.label)
        self.assertContains(response, "Conducted the SGLGB orientation")

    def test_no_staff_name_reaches_the_public_page(self):
        for url in (
            reverse("core:public_updates"),
            reverse("core:public_update_week", args=[self.period.pk]),
        ):
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("Matanguihan", body)
                self.assertNotIn("Rosalinda", body)

    def test_the_public_week_carries_the_division_statistics(self):
        """
        The public page is laid out as the convocation is, and carries the
        same five figures - the Division's totals for the week.
        """
        response = self.client.get(
            reverse("core:public_update_week", args=[self.period.pk])
        )
        self.assertContains(response, "Division Statistics")
        self.assertContains(response, "Weekly update completion")
        self.assertEqual(response.context["stats"]["accomplishments"], 1)
        self.assertEqual(response.context["stats"]["activities"], 1)

    def test_the_published_figures_state_the_division_total(self):
        """
        An uncleared entry still counts towards what the Division did that
        week; what it does not do is appear in the list underneath.
        """
        DivisionUpdate.objects.create(
            period=self.period,
            title="Internal staffing note",
            activity_date=LAST_MONDAY,
            is_public=False,
        )
        response = self.client.get(
            reverse("core:public_update_week", args=[self.period.pk])
        )
        self.assertEqual(response.context["stats"]["accomplishments"], 2)
        self.assertEqual(len(response.context["entries"]), 1)
        self.assertNotContains(response, "Internal staffing note")

    def test_pops_compliance_adds_up_to_the_table_beneath_it(self):
        """
        The headline percentage is computed from the published rows alone, so
        a reader can check it against the table without arriving elsewhere.
        """
        PopsPlanUpdate.objects.create(
            period=self.period, commitment="Published commitment",
            target=10, accomplished=5, is_public=True,
        )
        PopsPlanUpdate.objects.create(
            period=self.period, commitment="Withheld commitment",
            target=90, accomplished=90, is_public=False,
        )
        response = self.client.get(
            reverse("core:public_update_week", args=[self.period.pk])
        )
        compliance = response.context["pops_compliance"]
        self.assertEqual(compliance["target"], 10)
        self.assertEqual(compliance["accomplished"], 5)
        self.assertEqual(compliance["percent"], 50)
        self.assertNotContains(response, "Withheld commitment")


class WeekRecordFormTests(TestCase):
    """The records that hang off a week rather than off one entry."""

    @classmethod
    def setUpTestData(cls):
        cls.period = ReportingPeriod.objects.create(
            start_date=MONDAY, end_date=FRIDAY
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )

    def test_the_nested_forms_render_for_an_encoder(self):
        self.client.force_login(self.encoder)
        for name in ("updates:pops_create", "updates:way_create"):
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=[self.period.pk]))
                self.assertEqual(response.status_code, 200)

    def test_a_viewer_may_not_open_them(self):
        self.client.force_login(self.viewer)
        for name in ("updates:pops_create", "updates:way_create"):
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=[self.period.pk]))
                self.assertEqual(response.status_code, 403)

    def test_a_pops_figure_is_filed_against_the_week_and_returns_to_it(self):
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("updates:pops_create", args=[self.period.pk]),
            {
                "commitment": "Anti-illegal drugs operations monitored",
                "target": 4,
                "accomplished": 3,
                "remarks": "",
            },
        )
        self.assertRedirects(response, self.period.get_absolute_url())
        pops = PopsPlanUpdate.objects.get()
        self.assertEqual(pops.period, self.period)
        self.assertEqual(pops.recorded_by, self.encoder)
        self.assertEqual(pops.percent, 75)
        self.assertEqual(pops.status, "partial")

    def test_a_way_forward_is_filed_against_the_week(self):
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("updates:way_create", args=[self.period.pk]),
            {
                "description": "Draft the district-wide FDP advisory",
                "detail": "",
                "target_date": "",
                "status": "PENDING",
            },
        )
        self.assertRedirects(response, self.period.get_absolute_url())
        way = WayForward.objects.get()
        self.assertEqual(way.period, self.period)
        self.assertTrue(way.is_open)


class AttachmentTests(TestCase):
    """
    Photographs and supporting documents filed against an entry.

    Uploads go to a temporary root rather than to `media/`, so running the
    suite never leaves files behind in the working copy.
    """

    @classmethod
    def setUpClass(cls):
        cls.media_root = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.period = ReportingPeriod.objects.create(
            start_date=MONDAY, end_date=FRIDAY
        )
        cls.entry = DivisionUpdate.objects.create(
            period=cls.period,
            title="Conducted the SGLGB orientation",
            activity_date=MONDAY,
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )

    def upload(self, filename, mov_type="PHOTO", content=b"not really an image"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(
            reverse("updates:attachment_add", args=[self.entry.pk]),
            {
                "mov_type": mov_type,
                "caption": "Participants of the orientation",
                "file": SimpleUploadedFile(filename, content),
            },
        )

    def test_a_photograph_is_filed_against_the_entry(self):
        self.client.force_login(self.encoder)
        response = self.upload("orientation.jpg")
        self.assertRedirects(response, self.entry.get_absolute_url())

        photo = self.entry.photos.get()
        self.assertEqual(photo.uploaded_by, self.encoder)
        self.assertFalse(photo.is_public)
        # A caption is what a screen reader is given; the filename never is.
        self.assertEqual(photo.alt_text, "Participants of the orientation")

    def test_a_photograph_that_is_not_an_image_is_refused(self):
        self.client.force_login(self.encoder)
        self.upload("minutes.docx")
        self.assertEqual(self.entry.attachments.count(), 0)

    def test_a_viewer_may_not_attach_anything(self):
        self.client.force_login(self.viewer)
        response = self.upload("orientation.jpg")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.entry.attachments.count(), 0)

    def test_evidence_counts_towards_the_week_being_complete(self):
        self.client.force_login(self.encoder)
        self.assertIn("Means of verification", self.period.missing_components)
        self.upload("orientation.jpg")
        self.assertNotIn("Means of verification", self.period.missing_components)
