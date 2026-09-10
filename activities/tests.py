"""
What the calendar promises, tested.

The promises are about who may see and change what, so these tests are written
from the outside: they sign in as one employee and ask the server for another
employee's activity, by URL and by primary key, the way somebody would if they
were trying. A test that only called `visible_to()` would prove the queryset
right and leave open the question these tests exist to close - whether the
views actually use it.
"""

import datetime
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, Section, User

from .forms import CalendarActivityForm
from .models import (
    ActivityStatus,
    ActivityType,
    CalendarActivity,
    Priority,
    Visibility,
)

TODAY = timezone.localdate()


def make_activity(owner, **overrides):
    fields = {
        "title": f"{owner.username}'s activity",
        "activity_type": ActivityType.OFFICE_WORK,
        "start_date": TODAY,
        "visibility": Visibility.PRIVATE,
        "created_by": owner,
    }
    fields.update(overrides)
    return CalendarActivity.objects.create(owner=owner, **fields)


class CalendarTestCase(TestCase):
    """One Chief, two sections, three employees, and an administrator."""

    @classmethod
    def setUpTestData(cls):
        cls.field = Section.objects.create(name="Field Operations", short_name="FOS")
        cls.records = Section.objects.create(name="Records", short_name="ARS")

        cls.chief = User.objects.create_user(
            username="chief", password="x", role=Role.ADMIN,
            first_name="Divina", last_name="Chief", section=cls.field,
        )
        cls.admin = User.objects.create_user(
            username="ict", password="x", role=Role.SUPERADMIN,
            first_name="Ike", last_name="Tee",
        )
        cls.ana = User.objects.create_user(
            username="ana", password="x", role=Role.ENCODER,
            first_name="Ana", last_name="Reyes", section=cls.field,
        )
        cls.ben = User.objects.create_user(
            username="ben", password="x", role=Role.ENCODER,
            first_name="Ben", last_name="Cruz", section=cls.field,
        )
        cls.cora = User.objects.create_user(
            username="cora", password="x", role=Role.LGMED_STAFF,
            first_name="Cora", last_name="Lim", section=cls.records,
        )


class VisibilityTests(CalendarTestCase):
    def test_a_private_activity_is_visible_only_to_its_owner(self):
        activity = make_activity(self.ana)

        self.assertIn(activity, CalendarActivity.objects.visible_to(self.ana))
        self.assertNotIn(activity, CalendarActivity.objects.visible_to(self.ben))
        self.assertNotIn(activity, CalendarActivity.objects.visible_to(self.cora))

    def test_supervisors_see_every_activity_including_private_ones(self):
        activity = make_activity(self.ana)

        self.assertIn(activity, CalendarActivity.objects.visible_to(self.chief))
        self.assertIn(activity, CalendarActivity.objects.visible_to(self.admin))

    def test_a_team_activity_reaches_the_section_and_stops_there(self):
        activity = make_activity(
            self.ana, visibility=Visibility.TEAM, section=self.field
        )

        # Ben is in Field Operations with Ana; Cora is in Records.
        self.assertIn(activity, CalendarActivity.objects.visible_to(self.ben))
        self.assertNotIn(activity, CalendarActivity.objects.visible_to(self.cora))

    def test_an_office_wide_activity_reaches_everybody(self):
        activity = make_activity(self.ana, visibility=Visibility.ORGANIZATION)

        for person in (self.ben, self.cora, self.chief):
            with self.subTest(user=person.username):
                self.assertIn(
                    activity, CalendarActivity.objects.visible_to(person)
                )

    def test_the_assigned_employee_sees_an_activity_they_did_not_create(self):
        activity = make_activity(
            self.ana, visibility=Visibility.ASSIGNED, assigned_to=self.cora
        )

        # Cora is in another section and the activity is not office-wide; she
        # sees it because it is hers to do.
        self.assertIn(activity, CalendarActivity.objects.visible_to(self.cora))
        self.assertNotIn(activity, CalendarActivity.objects.visible_to(self.ben))

    def test_an_employee_without_a_section_is_not_shown_every_team_activity(self):
        """A null section must not match another null section."""
        nomad = User.objects.create_user(
            username="nomad", password="x", role=Role.ENCODER
        )
        activity = make_activity(self.ana, visibility=Visibility.TEAM, section=None)

        self.assertNotIn(activity, CalendarActivity.objects.visible_to(nomad))


class RecordAccessTests(CalendarTestCase):
    """The rules above, asked of the server over HTTP."""

    def test_another_employees_private_activity_is_not_found(self):
        activity = make_activity(self.ana)
        self.client.force_login(self.ben)

        response = self.client.get(activity.get_absolute_url())

        # 404 rather than 403: confirming that activity 7 exists but is not
        # Ben's is itself a disclosure.
        self.assertEqual(response.status_code, 404)

    def test_guessing_a_primary_key_does_not_open_a_private_activity(self):
        activity = make_activity(self.ana)
        self.client.force_login(self.cora)

        for name in ("activities:detail", "activities:update", "activities:delete"):
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=[activity.pk]))
                self.assertEqual(response.status_code, 404)

    def test_the_chief_may_open_any_activity(self):
        activity = make_activity(self.ana)
        self.client.force_login(self.chief)

        response = self.client.get(activity.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ana Reyes")

    def test_a_readable_activity_is_still_not_an_editable_one(self):
        """Visible to the whole office, and still nobody else's to change."""
        activity = make_activity(self.ana, visibility=Visibility.ORGANIZATION)
        self.client.force_login(self.ben)

        self.assertEqual(
            self.client.get(activity.get_absolute_url()).status_code, 200
        )
        self.assertEqual(
            self.client.get(
                reverse("activities:update", args=[activity.pk])
            ).status_code,
            403,
        )

    def test_the_chief_reads_but_does_not_rewrite(self):
        activity = make_activity(self.ana, visibility=Visibility.ORGANIZATION)
        self.client.force_login(self.chief)

        self.assertEqual(
            self.client.get(activity.get_absolute_url()).status_code, 200
        )
        self.assertEqual(
            self.client.get(
                reverse("activities:update", args=[activity.pk])
            ).status_code,
            403,
        )

    def test_an_administrator_may_edit_another_employees_activity(self):
        activity = make_activity(self.ana, visibility=Visibility.ORGANIZATION)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("activities:update", args=[activity.pk]))

        self.assertEqual(response.status_code, 200)

    def test_an_employee_may_delete_their_own_activity(self):
        activity = make_activity(self.ana)
        self.client.force_login(self.ana)

        response = self.client.post(reverse("activities:delete", args=[activity.pk]))

        self.assertRedirects(response, reverse("activities:list"))
        self.assertFalse(CalendarActivity.objects.filter(pk=activity.pk).exists())

    def test_a_colleague_cannot_delete_an_activity_they_can_see(self):
        activity = make_activity(self.ana, visibility=Visibility.ORGANIZATION)
        self.client.force_login(self.ben)

        response = self.client.post(reverse("activities:delete", args=[activity.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(CalendarActivity.objects.filter(pk=activity.pk).exists())


class OwnershipTests(CalendarTestCase):
    def test_an_employee_creating_an_activity_owns_it(self):
        self.client.force_login(self.ana)

        self.client.post(
            reverse("activities:create"),
            {
                "title": "Draft the quarterly matrix",
                "activity_type": ActivityType.OFFICE_WORK,
                "description": "",
                "start_date": TODAY.isoformat(),
                "end_date": "",
                "start_time": "",
                "end_time": "",
                "location": "",
                "lgu": "",
                "participants": "",
                "priority": Priority.NORMAL,
                "status": ActivityStatus.PLANNED,
                "visibility": Visibility.PRIVATE,
                "remarks": "",
            },
        )

        activity = CalendarActivity.objects.get(title="Draft the quarterly matrix")
        self.assertEqual(activity.owner, self.ana)
        self.assertEqual(activity.created_by, self.ana)

    def test_an_employee_cannot_file_an_activity_under_a_colleague(self):
        """The owner field is not offered to them, so posting it changes nothing."""
        self.client.force_login(self.ana)

        self.client.post(
            reverse("activities:create"),
            {
                "title": "Not Ben's to answer for",
                "owner": self.ben.pk,
                "activity_type": ActivityType.OFFICE_WORK,
                "description": "",
                "start_date": TODAY.isoformat(),
                "end_date": "",
                "start_time": "",
                "end_time": "",
                "location": "",
                "lgu": "",
                "participants": "",
                "priority": Priority.NORMAL,
                "status": ActivityStatus.PLANNED,
                "visibility": Visibility.PRIVATE,
                "remarks": "",
            },
        )

        activity = CalendarActivity.objects.get(title="Not Ben's to answer for")
        self.assertEqual(activity.owner, self.ana)

    def test_the_section_defaults_to_the_owners(self):
        activity = make_activity(self.cora)

        self.assertEqual(activity.section, self.records)

    def test_creator_and_assignee_are_told_apart(self):
        activity = make_activity(
            self.ana, visibility=Visibility.ASSIGNED, assigned_to=self.ben
        )

        self.assertTrue(activity.is_delegated)
        self.assertEqual(activity.owner, self.ana)
        self.assertEqual(activity.responsible, self.ben)

    def test_an_activity_the_owner_does_themselves_is_not_delegated(self):
        activity = make_activity(self.ana, assigned_to=self.ana)

        self.assertFalse(activity.is_delegated)
        self.assertEqual(activity.responsible, self.ana)


class QuickAddTests(CalendarTestCase):
    """
    The day dialog's short form.

    It posts to the ordinary create URL, so what is really under test is that
    the quick way in is not a way around anything: the same ownership rules,
    the same validation, and a redirect target that is checked before it is
    followed.
    """

    def quick_post(self, **overrides):
        data = {
            "quick": "1",
            "next": reverse("activities:list") + "?scope=mine&period=month",
            "title": "Added from the calendar",
            "activity_type": ActivityType.MEETING,
            "description": "",
            "assigned_to": "",
            "start_date": TODAY.isoformat(),
            "end_date": "",
            "start_time": "",
            "end_time": "",
            "location": "",
            "priority": Priority.NORMAL,
            "visibility": Visibility.PRIVATE,
        }
        data.update(overrides)
        return self.client.post(reverse("activities:create"), data)

    def test_the_dialog_carries_a_working_form_for_anyone_who_may_encode(self):
        self.client.force_login(self.ana)

        response = self.client.get(reverse("activities:list"))

        self.assertIsNotNone(response.context["quick_form"])
        self.assertContains(response, "data-day-form")
        self.assertContains(response, 'name="quick"')

    def test_a_viewer_is_offered_no_form_at_all(self):
        """The dialog still opens, to read the day. It offers nothing to save."""
        viewer = User.objects.create_user(
            username="vera", password="x", role=Role.VIEWER
        )
        self.client.force_login(viewer)

        response = self.client.get(reverse("activities:list"))

        self.assertIsNone(response.context["quick_form"])
        self.assertNotContains(response, "data-day-form")

    def test_a_quick_add_creates_the_activity_and_returns_to_the_calendar(self):
        self.client.force_login(self.ana)

        response = self.quick_post(start_time="09:30", end_time="11:00")

        activity = CalendarActivity.objects.get(title="Added from the calendar")
        self.assertEqual(activity.owner, self.ana)
        self.assertEqual(activity.created_by, self.ana)
        self.assertEqual(activity.section, self.field)
        self.assertEqual(activity.status, ActivityStatus.PLANNED)
        self.assertRedirects(
            response, reverse("activities:list") + "?scope=mine&period=month"
        )

    def test_the_quick_form_offers_no_way_to_file_under_a_colleague(self):
        self.client.force_login(self.ana)

        self.quick_post(owner=self.ben.pk)

        activity = CalendarActivity.objects.get(title="Added from the calendar")
        self.assertEqual(activity.owner, self.ana)

    def test_the_quick_form_still_refuses_an_assignee_who_could_not_see_it(self):
        """The short form inherits the full form's rules rather than restating them."""
        self.client.force_login(self.ana)

        response = self.quick_post(
            assigned_to=self.ben.pk, visibility=Visibility.PRIVATE
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            CalendarActivity.objects.filter(title="Added from the calendar").exists()
        )

    def test_an_invalid_quick_post_renders_the_form_with_its_errors(self):
        self.client.force_login(self.ana)

        response = self.quick_post(title="", start_date="")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(CalendarActivity.objects.count(), 0)

    def test_the_plainest_calendar_url_is_a_valid_return_address(self):
        """
        `/app/calendar/` with no query string is what `request.get_full_path`
        renders for most visits, so it is the return address most saves carry.
        A validator that only accepted the decorated form would send the common
        case to the record page instead of back to the calendar.
        """
        self.client.force_login(self.ana)

        response = self.quick_post(next=reverse("activities:list"))

        self.assertRedirects(response, reverse("activities:list"))

    def test_the_return_address_is_checked_before_it_is_followed(self):
        """`next` arrives in a form post; an unchecked one is an open redirect."""
        self.client.force_login(self.ana)

        response = self.quick_post(next="https://evil.example.com/phish")

        activity = CalendarActivity.objects.get(title="Added from the calendar")
        self.assertRedirects(response, activity.get_absolute_url())

    def test_a_viewer_cannot_post_the_quick_form_either(self):
        """The form is hidden from them; the view refuses them regardless."""
        viewer = User.objects.create_user(
            username="vic", password="x", role=Role.VIEWER
        )
        self.client.force_login(viewer)

        response = self.quick_post()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(CalendarActivity.objects.count(), 0)


class ProgressTests(CalendarTestCase):
    def test_the_assigned_employee_may_report_progress(self):
        activity = make_activity(
            self.ana, visibility=Visibility.ASSIGNED, assigned_to=self.ben
        )
        self.client.force_login(self.ben)

        self.client.post(
            reverse("activities:progress", args=[activity.pk]),
            {"status": ActivityStatus.COMPLETED, "remarks": "Submitted on time."},
        )

        activity.refresh_from_db()
        self.assertEqual(activity.status, ActivityStatus.COMPLETED)
        self.assertEqual(activity.remarks, "Submitted on time.")
        self.assertEqual(activity.updated_by, self.ben)

    def test_reporting_progress_is_not_a_way_to_edit_the_record(self):
        activity = make_activity(
            self.ana, visibility=Visibility.ASSIGNED, assigned_to=self.ben
        )
        self.client.force_login(self.ben)

        self.client.post(
            reverse("activities:progress", args=[activity.pk]),
            {
                "status": ActivityStatus.COMPLETED,
                "remarks": "",
                "title": "Renamed by the assignee",
                "visibility": Visibility.PRIVATE,
            },
        )

        activity.refresh_from_db()
        self.assertEqual(activity.title, "ana's activity")
        self.assertEqual(activity.visibility, Visibility.ASSIGNED)

    def test_a_bystander_may_not_report_progress(self):
        activity = make_activity(self.ana, visibility=Visibility.ORGANIZATION)
        self.client.force_login(self.cora)

        response = self.client.post(
            reverse("activities:progress", args=[activity.pk]),
            {"status": ActivityStatus.CANCELLED, "remarks": ""},
        )

        activity.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(activity.status, ActivityStatus.PLANNED)


class CalendarViewTests(CalendarTestCase):
    def test_the_month_grid_shows_only_what_the_viewer_may_see(self):
        make_activity(self.ana, title="Ana's private plan")
        make_activity(self.ben, title="Ben's open plan",
                      visibility=Visibility.ORGANIZATION)
        self.client.force_login(self.ben)

        response = self.client.get(reverse("activities:list"), {"scope": "shared"})

        self.assertNotContains(response, "Ana&#x27;s private plan")
        self.client.force_login(self.chief)
        response = self.client.get(reverse("activities:list"), {"scope": "all"})
        self.assertContains(response, "Ana&#x27;s private plan")

    def test_asking_for_everyones_calendar_without_the_capability_shows_your_own(self):
        make_activity(self.ana, title="Ana's private plan")
        make_activity(self.ben, title="Ben's own plan")
        self.client.force_login(self.ben)

        response = self.client.get(reverse("activities:list"), {"scope": "all"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Ana&#x27;s private plan")
        self.assertContains(response, "Ben&#x27;s own plan")

    def test_the_overdue_view_lists_unfinished_work_that_has_passed(self):
        make_activity(
            self.ana, title="Late report",
            start_date=TODAY - datetime.timedelta(days=3),
        )
        make_activity(
            self.ana, title="Report already filed",
            start_date=TODAY - datetime.timedelta(days=3),
            status=ActivityStatus.COMPLETED,
        )
        self.client.force_login(self.ana)

        response = self.client.get(reverse("activities:list"), {"period": "overdue"})

        self.assertContains(response, "Late report")
        self.assertNotContains(response, "Report already filed")

    def test_a_multi_day_activity_is_not_overdue_on_its_second_morning(self):
        activity = make_activity(
            self.ana,
            start_date=TODAY - datetime.timedelta(days=1),
            end_date=TODAY + datetime.timedelta(days=3),
        )

        self.assertFalse(activity.is_overdue)
        self.assertNotIn(activity, CalendarActivity.objects.overdue())

    def test_a_long_title_reaches_the_grid_whole(self):
        """
        The day cell wraps the title in CSS and clamps it at three lines. The
        server must therefore send the whole thing: shortening it here as well
        would truncate an already-truncated title, and the tooltip and the day
        dialog would both be short too.
        """
        title = (
            "Barangay Development Plan Orientation and Consultation Workshop "
            "for Agusan del Norte"
        )
        make_activity(self.ana, title=title, start_date=TODAY.replace(day=22))
        self.client.force_login(self.ana)

        html = self.client.get(reverse("activities:list")).content.decode()
        grid = html.split("data-day-panels")[0]

        # In the cell itself, not merely somewhere on the page: the grid is
        # where the shortening would be applied if anyone applied it.
        self.assertIn(title, grid)

    def test_a_start_time_with_minutes_is_not_rounded_down_in_the_grid(self):
        """
        The day cell abbreviates the time to save room. It may not abbreviate
        it into a different time: "9AM" for a 9:45 briefing is wrong, not brief.
        """
        day = TODAY.replace(day=15)
        make_activity(
            self.ana, title="Quarter-to briefing", start_date=day,
            start_time=datetime.time(9, 45),
        )
        make_activity(
            self.ana, title="On the hour", start_date=day,
            start_time=datetime.time(8, 0),
        )
        self.client.force_login(self.ana)

        html = self.client.get(reverse("activities:list")).content.decode()

        self.assertIn("9:45AM", html)
        self.assertNotIn("9AM", html)
        # The hour alone is right when the hour is all there is.
        self.assertIn("8AM", html)

    def test_each_dialog_has_exactly_one_scroll_container(self):
        """
        Nested scrollers put two scrollbars side by side and make the outer one
        useless. Each dialog caps its height on an inner wrapper and scrolls in
        one place, with the heading and the buttons pinned either side.
        """
        make_activity(self.ana, title="Something to preview")
        self.client.force_login(self.ana)

        html = self.client.get(reverse("activities:list")).content.decode()

        for dialog_id in ("day-peek", "activity-peek"):
            with self.subTest(dialog=dialog_id):
                start = html.rfind("<dialog", 0, html.find(f'id="{dialog_id}"'))
                markup = html[start:html.find("</dialog>", start)]
                self.assertEqual(markup.count("overflow-y-auto"), 1)
                self.assertEqual(markup.count("max-h-[85vh]"), 1)

    def test_the_dialogs_do_not_put_display_flex_on_the_dialog_itself(self):
        """
        An author `display:flex` beats the browser's own
        `dialog:not([open]) { display: none }` - author styles outrank the
        user-agent sheet whatever the specificity - and the dialog would sit on
        the page permanently, open or not. The flex column goes on a wrapper.
        """
        self.client.force_login(self.ana)

        html = self.client.get(reverse("activities:list")).content.decode()

        for tag in re.findall(r"<dialog[^>]*>", html):
            with self.subTest(tag=tag[:60]):
                classes = re.search(r'class="([^"]*)"', tag)
                self.assertNotIn("flex", (classes.group(1) if classes else "").split())

    def test_the_save_button_reaches_the_form_it_sits_outside_of(self):
        """The buttons are pinned below the scroll area, so they submit by id."""
        self.client.force_login(self.ana)

        html = self.client.get(reverse("activities:list")).content.decode()

        self.assertIn('id="day-peek-form"', html)
        self.assertIn('form="day-peek-form"', html)

    def test_the_search_and_filter_bar_appears_once(self):
        """
        It is rendered above both columns, not inside the list card. Two
        toolbars on one page would give two search boxes with one id.
        """
        self.client.force_login(self.chief)

        html = self.client.get(reverse("activities:list")).content.decode()

        self.assertEqual(html.count('id="table-search"'), 1)
        self.assertLess(
            html.find("Search and filter activities"), html.find("calendar-heading")
        )

    def test_the_whole_day_box_opens_the_day_not_just_the_numeral(self):
        """
        The cell carries the link and the data the dialog is built from. It
        stays an ordinary link, so a browser without scripting still gets the
        day listed beside the grid.
        """
        day = TODAY.replace(day=15)
        make_activity(self.ana, title="Mid-month meeting", start_date=day)
        self.client.force_login(self.ana)

        response = self.client.get(reverse("activities:list"))
        html = response.content.decode()

        self.assertIn(f'data-day="{day.isoformat()}"', html)
        self.assertIn(f'href="?day={day.isoformat()}"', html)
        # One overlay per cell in a six-week grid, and never more than one.
        self.assertEqual(html.count("data-day-open"), html.count('data-day="'))

    def test_a_busy_day_caps_the_cell_but_not_the_dialog(self):
        """
        Three fit in a day cell; the dialog gets all of them, from markup the
        server already scoped rather than from a request of its own.
        """
        day = TODAY.replace(day=15)
        for index in range(5):
            make_activity(self.ana, title=f"Busy item {index}", start_date=day)
        self.client.force_login(self.ana)

        html = self.client.get(reverse("activities:list")).content.decode()
        grid, panels = html.split("data-day-panels", 1)

        self.assertIn("+2 more", grid)
        for index in range(5):
            with self.subTest(activity=index):
                self.assertIn(f"Busy item {index}", panels)

    def test_the_day_panels_carry_nothing_the_viewer_may_not_see(self):
        """The dialog ships with the page, so it must be scoped like the page."""
        day = TODAY.replace(day=15)
        make_activity(self.ana, title="Ana's private errand", start_date=day)
        make_activity(
            self.ben, title="Ben's own errand", start_date=day,
        )
        self.client.force_login(self.ben)

        html = self.client.get(reverse("activities:list")).content.decode()

        self.assertIn("Ben&#x27;s own errand", html)
        self.assertNotIn("Ana&#x27;s private errand", html)

    def test_opening_a_day_outside_the_loaded_month_still_answers(self):
        """The day panel asks the database, rather than sifting the month."""
        day = TODAY + datetime.timedelta(days=75)
        make_activity(self.ana, title="Far-off validation", start_date=day)
        self.client.force_login(self.ana)

        response = self.client.get(
            reverse("activities:list"), {"day": day.isoformat()}
        )

        self.assertContains(response, "Far-off validation")

    def test_the_day_panel_shows_nothing_a_colleague_may_not_see(self):
        day = TODAY + datetime.timedelta(days=3)
        make_activity(self.ana, title="Ana's private errand", start_date=day)
        self.client.force_login(self.ben)

        response = self.client.get(
            reverse("activities:list"), {"day": day.isoformat()}
        )

        self.assertNotContains(response, "Ana&#x27;s private errand")

    def test_a_date_range_replaces_the_period_rather_than_narrowing_it(self):
        """
        A range and a month are two answers to the same question. Applying
        both would hand back their intersection, which is usually empty.
        """
        make_activity(
            self.ana, title="Next quarter planning",
            start_date=TODAY + datetime.timedelta(days=120),
        )
        self.client.force_login(self.ana)

        response = self.client.get(
            reverse("activities:list"),
            {
                "period": "month",
                "from": (TODAY + datetime.timedelta(days=100)).isoformat(),
                "to": (TODAY + datetime.timedelta(days=140)).isoformat(),
            },
        )

        self.assertContains(response, "Next quarter planning")
        # The month grid is stood down: it would show this month's calendar
        # beside the activities of a range four months away.
        self.assertFalse(response.context["show_month_grid"])

    def test_the_csv_export_carries_only_permitted_activities(self):
        make_activity(self.ana, title="Ana's private plan")
        make_activity(self.ben, title="Ben's own plan")
        self.client.force_login(self.ben)

        response = self.client.get(reverse("activities:list"), {"export": "csv"})
        body = response.content.decode("utf-8-sig")

        self.assertIn("Ben's own plan", body)
        self.assertNotIn("Ana's private plan", body)

    def test_the_monitoring_page_is_refused_to_ordinary_employees(self):
        self.client.force_login(self.ana)

        self.assertEqual(
            self.client.get(reverse("activities:monitor")).status_code, 403
        )

    def test_the_monitoring_page_reports_each_employees_workload(self):
        make_activity(self.ana)
        make_activity(self.ana, start_date=TODAY + datetime.timedelta(days=5))
        self.client.force_login(self.chief)

        response = self.client.get(reverse("activities:monitor"))

        self.assertEqual(response.status_code, 200)
        row = next(
            person
            for person in response.context["workload"]
            if person.pk == self.ana.pk
        )
        self.assertEqual(row.open_count, 2)


class ActivityFormTests(CalendarTestCase):
    def base_data(self, **overrides):
        data = {
            "title": "Validation visit",
            "activity_type": ActivityType.MONITORING,
            "description": "",
            "start_date": TODAY.isoformat(),
            "end_date": "",
            "start_time": "",
            "end_time": "",
            "location": "",
            "lgu": "",
            "participants": "",
            "priority": Priority.NORMAL,
            "status": ActivityStatus.PLANNED,
            "visibility": Visibility.PRIVATE,
            "remarks": "",
        }
        data.update(overrides)
        return data

    def test_an_employee_is_not_offered_the_owner_field(self):
        form = CalendarActivityForm(user=self.ana)

        self.assertNotIn("owner", form.fields)

    def test_a_supervisor_is_offered_the_owner_field(self):
        form = CalendarActivityForm(user=self.chief)

        self.assertIn("owner", form.fields)

    def test_publishing_is_offered_only_to_the_approving_roles(self):
        self.assertNotIn(
            "is_published", CalendarActivityForm(user=self.ana).fields
        )
        self.assertIn(
            "is_published", CalendarActivityForm(user=self.cora).fields
        )

    def test_a_private_activity_cannot_be_published_publicly(self):
        form = CalendarActivityForm(
            data=self.base_data(
                visibility=Visibility.PRIVATE, is_published="on"
            ),
            user=self.cora,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("is_published", form.errors)

    def test_an_assignee_who_could_not_see_the_activity_is_refused(self):
        form = CalendarActivityForm(
            data=self.base_data(
                assigned_to=self.ben.pk, visibility=Visibility.PRIVATE
            ),
            user=self.ana,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("visibility", form.errors)

    def test_the_end_time_must_follow_the_start_time(self):
        form = CalendarActivityForm(
            data=self.base_data(start_time="14:00", end_time="09:00"),
            user=self.ana,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("end_time", form.errors)

    def test_the_end_date_must_not_precede_the_start_date(self):
        form = CalendarActivityForm(
            data=self.base_data(
                end_date=(TODAY - datetime.timedelta(days=1)).isoformat()
            ),
            user=self.ana,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("end_date", form.errors)
