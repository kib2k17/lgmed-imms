"""Tests for the Frontline Services module."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User

from .models import FrontlineService, ServiceType


def service_post(**overrides):
    data = {
        "name": "Technical assistance on SGLG",
        "service_type": ServiceType.SIMPLE,
        "description": "Assistance to LGUs preparing for the assessment.",
        "clients": "LGUs",
        "requirements": "Letter of request\nList of attendees\n",
        "processing_time": "3 working days",
        "fees": "None",
        "responsible_office": "LGMED",
        "responsible_person": "Section chief",
    }
    data.update(overrides)
    return data


class FrontlineServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="admin", password="pw", role=Role.ADMIN)
        cls.staff = User.objects.create_user(username="staff", password="pw", role=Role.LGMED_STAFF)
        cls.encoder = User.objects.create_user(username="encoder", password="pw", role=Role.ENCODER)
        cls.viewer = User.objects.create_user(username="viewer", password="pw", role=Role.VIEWER)
        cls.service = FrontlineService.objects.create(
            name="Orientation on CapDev", requirements="Request letter\n\n  Agenda  \n",
        )

    def test_requirements_are_listed_one_per_line(self):
        self.assertEqual(self.service.requirement_list, ["Request letter", "Agenda"])

    def test_every_role_reads_the_list_and_the_record(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("services:list")), "Orientation on CapDev")
        self.assertEqual(self.client.get(self.service.get_absolute_url()).status_code, 200)

    def test_a_viewer_cannot_add_or_change_a_service(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("services:create")).status_code, 403)
        response = self.client.post(reverse("services:create"), service_post())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(FrontlineService.objects.filter(name="Technical assistance on SGLG").exists())

    def test_an_encoder_adds_a_service_but_cannot_publish_it(self):
        self.client.force_login(self.encoder)
        self.client.post(reverse("services:create"), service_post(is_published="on"))
        created = FrontlineService.objects.get(name="Technical assistance on SGLG")
        self.assertFalse(created.is_published)
        self.assertEqual(created.created_by, self.encoder)

    def test_an_approver_publishes_a_service(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("services:update", args=[self.service.pk]),
            service_post(name=self.service.name, is_published="on"),
        )
        self.service.refresh_from_db()
        self.assertTrue(self.service.is_published)

    def test_only_administrators_delete(self):
        url = reverse("services:delete", args=[self.service.pk])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(url)
        self.assertFalse(FrontlineService.objects.filter(pk=self.service.pk).exists())

    def test_the_list_filters_by_type_and_exports(self):
        FrontlineService.objects.create(name="Validation visit", service_type=ServiceType.TECHNICAL)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("services:list"), {"service_type": ServiceType.TECHNICAL})
        self.assertContains(response, "Validation visit")
        self.assertNotContains(response, "Orientation on CapDev")

        export = self.client.get(reverse("services:list"), {"export": "csv"})
        body = b"".join(export.streaming_content).decode("utf-8-sig")
        self.assertIn("Orientation on CapDev", body)
        self.assertIn("Validation visit", body)
