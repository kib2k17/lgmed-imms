"""
Tests for the analytics page and for the Phase 4 additions to the shared
module layer: date-range filtering, multi-value filters and audited exports.
"""

import datetime

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from analytics import metrics
from audit.models import Action, AuditEvent
from lgus.models import LGU, LGUType, Province
from monitoring.models import MonitoringActivity, MonitoringStatus
from reports.models import Report, ReportPeriod, ReportStatus


def make_region():
    north = Province.objects.create(name="Agusan del Norte")
    south = Province.objects.create(name="Surigao del Sur")
    city = LGU.objects.create(
        name="Cabadbaran City", lgu_type=LGUType.CITY, province=north
    )
    town = LGU.objects.create(
        name="Carmen", lgu_type=LGUType.MUNICIPALITY, province=south
    )
    unreached = LGU.objects.create(
        name="Lanuza", lgu_type=LGUType.MUNICIPALITY, province=south
    )
    return north, south, city, town, unreached


class MetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.north, cls.south, cls.city, cls.town, cls.unreached = make_region()
        for month in (2, 3, 3):
            MonitoringActivity.objects.create(
                title="SGLG Assessment",
                lgu=cls.city,
                monitoring_date=datetime.date(2026, month, 10),
                monitoring_team="M. Salazar",
                status=MonitoringStatus.COMPLETED,
            )
        MonitoringActivity.objects.create(
            title="Compliance check",
            lgu=cls.town,
            monitoring_date=datetime.date(2025, 5, 4),
            monitoring_team="R. Antonio",
            status=MonitoringStatus.COMPLETED,
        )

    def test_coverage_counts_lgus_reached_not_activities(self):
        """Three visits to one LGU is one LGU covered, not three."""
        headline = metrics.headline(2026)
        self.assertEqual(headline["activities"], 3)
        self.assertEqual(headline["lgus_covered"], 1)
        self.assertEqual(headline["lgus_total"], 3)
        self.assertEqual(headline["coverage_percent"], 33)

    def test_the_trend_compares_against_the_previous_year(self):
        chart = metrics.monitoring_trend(2026)
        self.assertEqual(chart["data"]["current"][2], 2)   # March 2026
        self.assertEqual(chart["data"]["previous"][4], 1)  # May 2025
        self.assertEqual(chart["data"]["currentLabel"], "2026")

    def test_province_figures_are_scoped_to_the_year(self):
        chart = metrics.monitoring_by_province(2026)
        figures = dict(zip(chart["data"]["labels"], chart["data"]["conducted"]))
        self.assertEqual(figures["Agusan del Norte"], 3)
        self.assertEqual(figures["Surigao del Sur"], 0)

    def test_least_monitored_puts_unreached_lgus_first(self):
        worst = list(metrics.least_monitored(2026, limit=3))
        self.assertEqual(worst[0].visits, 0)
        self.assertIn(worst[0].name, {"Carmen", "Lanuza"})
        self.assertEqual(worst[-1].name, "Cabadbaran City")

    def test_turnaround_is_none_when_no_report_completed_the_cycle(self):
        self.assertIsNone(metrics.report_turnaround(2026))

    def test_turnaround_averages_submission_to_publication(self):
        for submitted, published in [((3, 1), (3, 11)), ((4, 1), (4, 21))]:
            Report.objects.create(
                title=f"Report {submitted}",
                period=ReportPeriod.MONTHLY,
                year=2026,
                status=ReportStatus.PUBLISHED,
                submitted_on=datetime.date(2026, *submitted),
                published_on=datetime.date(2026, *published),
            )
        # 10 days and 20 days -> 15
        self.assertEqual(metrics.report_turnaround(2026), 15)

    def test_every_chart_carries_its_own_figures(self):
        """
        The table under each chart is what makes the page readable without it.

        Every row must line up with the headers; a chart with nothing to show
        legitimately has no rows, and says so through `has_data`.
        """
        for chart in metrics.charts(2026):
            with self.subTest(chart=chart["id"]):
                self.assertTrue(chart["headers"], "chart declares no headers")
                for row in chart["rows"]:
                    self.assertEqual(
                        len(row),
                        len(chart["headers"]),
                        f"{chart['id']}: row {row} does not match its headers",
                    )
                if chart["has_data"]:
                    self.assertTrue(
                        chart["rows"], f"{chart['id']}: has data but no figures"
                    )


class AnalyticsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_region()
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )

    def test_the_page_requires_sign_in(self):
        response = self.client.get(reverse("analytics:index"))
        self.assertEqual(response.status_code, 302)

    def test_every_role_may_read_the_analysis(self):
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.get(reverse("analytics:index")).status_code, 200
        )

    def test_an_unknown_year_falls_back_rather_than_erroring(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("analytics:index"), {"year": "not-a-year"})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("analytics:index"), {"year": "1900"})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.context["year"], 1900)

    def test_the_export_contains_every_chart_and_is_logged(self):
        self.client.force_login(self.viewer)
        AuditEvent.objects.filter(action=Action.EXPORT).delete()

        response = self.client.get(
            reverse("analytics:index"), {"year": 2026, "export": "csv"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])

        body = response.content.decode("utf-8-sig")
        for title in ("Monitoring by Province", "LGU Compliance",
                      "Least-monitored LGUs"):
            self.assertIn(title, body)

        self.assertTrue(
            AuditEvent.objects.filter(action=Action.EXPORT).exists()
        )


class AdvancedFilteringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _, _, cls.city, cls.town, _ = make_region()
        cls.march = MonitoringActivity.objects.create(
            title="March activity",
            lgu=cls.city,
            monitoring_date=datetime.date(2026, 3, 10),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.COMPLETED,
        )
        cls.august = MonitoringActivity.objects.create(
            title="August activity",
            lgu=cls.town,
            monitoring_date=datetime.date(2026, 8, 20),
            monitoring_team="R. Antonio",
            status=MonitoringStatus.FOR_REVIEW,
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_a_date_range_narrows_the_list(self):
        response = self.client.get(
            reverse("monitoring:list"), {"from": "2026-07-01", "to": "2026-12-31"}
        )
        self.assertEqual(list(response.context["records"]), [self.august])
        self.assertTrue(response.context["is_filtered"])

    def test_an_open_ended_range_is_allowed(self):
        response = self.client.get(reverse("monitoring:list"), {"from": "2026-06-01"})
        self.assertEqual(list(response.context["records"]), [self.august])

    def test_repeating_a_filter_selects_any_of_the_values(self):
        response = self.client.get(
            reverse("monitoring:list"),
            {"status": [MonitoringStatus.COMPLETED, MonitoringStatus.FOR_REVIEW]},
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 2)

    def test_the_export_honours_the_date_range(self):
        response = self.client.get(
            reverse("monitoring:list"),
            {"export": "csv", "from": "2026-07-01"},
        )
        body = response.content.decode("utf-8-sig")
        self.assertIn("August activity", body)
        self.assertNotIn("March activity", body)

    def test_exporting_is_recorded_in_the_audit_trail(self):
        AuditEvent.objects.filter(action=Action.EXPORT).delete()
        self.client.get(reverse("monitoring:list"), {"export": "csv"})

        entry = AuditEvent.objects.get(action=Action.EXPORT)
        self.assertEqual(entry.actor, self.staff)
        self.assertIn("2", entry.detail)

    def test_a_filtered_export_says_so_in_the_log(self):
        AuditEvent.objects.filter(action=Action.EXPORT).delete()
        self.client.get(
            reverse("monitoring:list"), {"export": "csv", "from": "2026-07-01"}
        )
        entry = AuditEvent.objects.get(action=Action.EXPORT)
        self.assertIn("matching the active filters", entry.detail)
