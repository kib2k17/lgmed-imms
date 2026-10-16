"""Tests for the LGU directory."""

import datetime

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse

from accounts.models import Role, User
from monitoring.models import MonitoringActivity, MonitoringStatus

from .models import LGU, ComplianceStatus, LGUType, Province


class LGUTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="admin", password="pw", role=Role.ADMIN)
        cls.encoder = User.objects.create_user(username="encoder", password="pw", role=Role.ENCODER)
        cls.viewer = User.objects.create_user(username="viewer", password="pw", role=Role.VIEWER)
        cls.agusan = Province.objects.create(name="Agusan del Norte")
        cls.surigao = Province.objects.create(name="Surigao del Sur")
        cls.butuan = LGU.objects.create(
            name="Butuan City", lgu_type=LGUType.CITY, province=cls.agusan, is_independent=True,
        )
        cls.tandag = LGU.objects.create(
            name="Tandag City", lgu_type=LGUType.CITY, province=cls.surigao,
            compliance_status=ComplianceStatus.COMPLIANT,
        )

    def monitor(self, lgu, when):
        return MonitoringActivity.objects.create(
            title="Visit", lgu=lgu, monitoring_date=when, status=MonitoringStatus.COMPLETED,
        )

    def test_a_name_is_unique_within_its_province_only(self):
        LGU.objects.create(name="San Jose", lgu_type=LGUType.MUNICIPALITY, province=self.agusan)
        LGU.objects.create(name="San Jose", lgu_type=LGUType.MUNICIPALITY, province=self.surigao)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LGU.objects.create(name="San Jose", lgu_type=LGUType.MUNICIPALITY, province=self.agusan)

    def test_the_latest_monitoring_and_compliance_tone(self):
        self.monitor(self.butuan, datetime.date(2026, 3, 1))
        self.monitor(self.butuan, datetime.date(2026, 8, 1))
        self.assertEqual(self.butuan.latest_monitoring_date, datetime.date(2026, 8, 1))
        self.assertEqual(self.butuan.monitoring_count, 2)
        self.assertIsNone(self.tandag.latest_monitoring_date)
        self.assertEqual(self.tandag.compliance_tone, "compliant")
        self.assertEqual(self.butuan.compliance_tone, "not_started")

    def test_the_list_filters_by_province(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("lgus:list"), {"province": self.surigao.pk})
        self.assertContains(response, "Tandag City")
        self.assertNotContains(response, "Butuan City")
        self.assertEqual(response.context["summary"]["cities"], 2)

    def test_an_encoder_adds_an_lgu_and_a_viewer_cannot(self):
        data = {
            "name": "Cabadbaran City", "lgu_type": LGUType.CITY, "province": self.agusan.pk,
            "income_class": "", "compliance_status": ComplianceStatus.NOT_ASSESSED,
            "is_active": "on",
        }
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("lgus:create"), data).status_code, 403)
        self.client.force_login(self.encoder)
        self.client.post(reverse("lgus:create"), data)
        self.assertTrue(LGU.objects.filter(name="Cabadbaran City").exists())

    def test_deleting_an_lgu_with_monitoring_records_is_refused_plainly(self):
        self.monitor(self.butuan, datetime.date(2026, 5, 1))
        self.client.force_login(self.admin)
        response = self.client.post(reverse("lgus:delete", args=[self.butuan.pk]), follow=True)
        self.assertEqual(response.status_code, 200)        # not a server error
        self.assertContains(response, "cannot be deleted")
        self.assertTrue(LGU.objects.filter(pk=self.butuan.pk).exists())

    def test_deleting_an_lgu_without_records_works(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("lgus:delete", args=[self.tandag.pk]))
        self.assertFalse(LGU.objects.filter(pk=self.tandag.pk).exists())

    def test_the_export_reads_the_latest_monitoring_without_a_query_per_row(self):
        for number in range(12):
            lgu = LGU.objects.create(
                name=f"Municipality {number}", lgu_type=LGUType.MUNICIPALITY, province=self.agusan,
            )
            self.monitor(lgu, datetime.date(2026, 6, number + 1))
        self.client.force_login(self.viewer)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("lgus:list"), {"export": "csv"})
            body = b"".join(response.streaming_content).decode("utf-8-sig")
        self.assertIn("2026-06-12", body)
        self.assertLess(len(queries), 15)
