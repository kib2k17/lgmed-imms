"""
Tests for the module machinery, exercised through the Monitoring module.

Search, filtering, sorting, pagination, export and the permission rules all
live in `core.views_base`, so proving them here proves them for every module.
"""

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from lgus.models import LGU, LGUType, Province
from monitoring.models import MonitoringActivity, MonitoringStatus


class MonitoringModuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.province = Province.objects.create(name="Agusan del Norte")
        cls.other_province = Province.objects.create(name="Surigao del Sur")
        cls.city = LGU.objects.create(
            name="Cabadbaran City", lgu_type=LGUType.CITY, province=cls.province
        )
        cls.town = LGU.objects.create(
            name="Carmen", lgu_type=LGUType.MUNICIPALITY, province=cls.other_province
        )

        cls.completed = MonitoringActivity.objects.create(
            title="SGLG Assessment",
            lgu=cls.city,
            monitoring_date=datetime.date(2026, 3, 2),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.COMPLETED,
        )
        cls.for_review = MonitoringActivity.objects.create(
            title="Full Disclosure Policy Check",
            lgu=cls.town,
            monitoring_date=datetime.date(2026, 5, 20),
            monitoring_team="R. Antonio",
            status=MonitoringStatus.FOR_REVIEW,
        )

        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )

    # -- the progress indicator -----------------------------------------

    def test_a_completed_record_shows_every_stage_as_done(self):
        """The last stage is the end of the road, not the step being worked on."""
        states = [stage["state"] for stage in self.completed.timeline]
        self.assertEqual(states, ["done"] * 4)

    def test_an_unfinished_record_still_marks_its_current_stage(self):
        states = [stage["state"] for stage in self.for_review.timeline]
        self.assertEqual(states, ["done", "done", "current", "upcoming"])

    # -- list behaviour -------------------------------------------------

    def test_search_matches_title_and_lgu(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("monitoring:list"), {"q": "Cabadbaran"})
        self.assertEqual(list(response.context["records"]), [self.completed])

    def test_filter_by_status(self):
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("monitoring:list"), {"status": MonitoringStatus.FOR_REVIEW}
        )
        self.assertEqual(list(response.context["records"]), [self.for_review])

    def test_filter_by_province_traverses_the_relation(self):
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("monitoring:list"), {"lgu__province": self.province.pk}
        )
        self.assertEqual(list(response.context["records"]), [self.completed])

    def test_sorting_is_restricted_to_the_whitelist(self):
        self.client.force_login(self.viewer)

        ascending = self.client.get(reverse("monitoring:list"), {"sort": "monitoring_date"})
        self.assertEqual(
            list(ascending.context["records"]), [self.completed, self.for_review]
        )

        # An unlisted column must not reach the ORM; the default order stands.
        injected = self.client.get(reverse("monitoring:list"), {"sort": "lgu__province__id"})
        self.assertEqual(
            list(injected.context["records"]), [self.for_review, self.completed]
        )

    def test_search_and_filter_combine(self):
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("monitoring:list"),
            {"q": "Policy", "status": MonitoringStatus.COMPLETED},
        )
        self.assertEqual(list(response.context["records"]), [])
        self.assertTrue(response.context["is_filtered"])

    def test_csv_export_respects_the_active_filters(self):
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("monitoring:list"),
            {"export": "csv", "status": MonitoringStatus.FOR_REVIEW},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment;", response["Content-Disposition"])

        body = response.content.decode("utf-8-sig")
        self.assertIn("Full Disclosure Policy Check", body)
        self.assertNotIn("SGLG Assessment", body)

    # -- permissions ----------------------------------------------------

    def test_viewer_cannot_open_the_create_form(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("monitoring:create")).status_code, 403)

    def test_viewer_cannot_post_a_new_record(self):
        """The refusal is on the POST, not merely on the hidden button."""
        self.client.force_login(self.viewer)
        before = MonitoringActivity.objects.count()
        response = self.client.post(
            reverse("monitoring:create"),
            {
                "title": "Unauthorised entry",
                "lgu": self.city.pk,
                "monitoring_date": "2026-06-01",
                "monitoring_team": "Nobody",
                "status": MonitoringStatus.SCHEDULED,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(MonitoringActivity.objects.count(), before)

    def test_encoder_can_create_and_is_recorded_as_the_author(self):
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("monitoring:create"),
            {
                "title": "Local Development Council Assessment",
                "lgu": self.city.pk,
                "monitoring_date": "2026-06-01",
                "monitoring_team": "J. Bacon",
                "status": MonitoringStatus.SCHEDULED,
                "findings": "",
                "recommendations": "",
                "follow_up_action": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        record = MonitoringActivity.objects.get(
            title="Local Development Council Assessment"
        )
        self.assertEqual(record.created_by, self.encoder)

    def test_encoder_cannot_delete(self):
        self.client.force_login(self.encoder)
        url = reverse("monitoring:delete", args=[self.completed.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(
            MonitoringActivity.objects.filter(pk=self.completed.pk).exists()
        )

    def test_administrator_can_delete_after_confirmation(self):
        self.client.force_login(self.admin)
        url = reverse("monitoring:delete", args=[self.completed.pk])

        self.assertContains(self.client.get(url), "cannot be undone")

        response = self.client.post(url)
        self.assertRedirects(response, reverse("monitoring:list"))
        self.assertFalse(
            MonitoringActivity.objects.filter(pk=self.completed.pk).exists()
        )

    # -- model behaviour -------------------------------------------------

    def test_follow_up_date_in_the_past_marks_the_record_overdue(self):
        record = MonitoringActivity.objects.create(
            title="Overdue follow-up",
            lgu=self.city,
            monitoring_date=timezone.localdate() - datetime.timedelta(days=60),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.FOR_REVIEW,
            follow_up_date=timezone.localdate() - datetime.timedelta(days=10),
        )
        self.assertTrue(record.is_overdue)
        self.assertEqual(record.display_status, "overdue")

    def test_completed_record_is_never_overdue(self):
        record = MonitoringActivity.objects.create(
            title="Closed out",
            lgu=self.city,
            monitoring_date=timezone.localdate() - datetime.timedelta(days=60),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.COMPLETED,
            follow_up_date=timezone.localdate() - datetime.timedelta(days=10),
        )
        self.assertFalse(record.is_overdue)

    def test_form_rejects_a_follow_up_before_the_monitoring_date(self):
        from monitoring.forms import MonitoringActivityForm

        form = MonitoringActivityForm(
            {
                "title": "Backwards dates",
                "lgu": self.city.pk,
                "monitoring_date": "2026-06-10",
                "monitoring_team": "M. Salazar",
                "status": MonitoringStatus.SCHEDULED,
                "follow_up_date": "2026-06-01",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("follow_up_date", form.errors)
