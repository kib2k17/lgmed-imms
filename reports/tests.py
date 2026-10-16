"""Tests for the Reports module."""

import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User

from .models import Report, ReportPeriod, ReportStatus


def report_post(**overrides):
    data = {
        "title": "Q3 SGLG monitoring report",
        "reference_number": "LGMED-RPT-2026-03",
        "period": ReportPeriod.QUARTERLY,
        "year": 2026,
        "summary": "Summary of the quarter.",
        "prepared_by": "Monitoring team",
        "status": ReportStatus.SUBMITTED,
        "review_remarks": "",
    }
    data.update(overrides)
    return data


class ReportWorkflowDateTests(TestCase):
    def test_a_draft_has_no_workflow_dates(self):
        report = Report.objects.create(title="Draft", year=2026)
        self.assertIsNone(report.submitted_on)
        self.assertIsNone(report.published_on)
        self.assertTrue(report.is_pending)

    def test_leaving_draft_stamps_the_submission_date_once(self):
        report = Report.objects.create(title="R", year=2026, status=ReportStatus.SUBMITTED)
        self.assertEqual(report.submitted_on, timezone.localdate())
        report.submitted_on = datetime.date(2026, 1, 5)
        report.status = ReportStatus.FOR_REVIEW
        report.save()
        self.assertEqual(report.submitted_on, datetime.date(2026, 1, 5))

    def test_publication_date_follows_the_status(self):
        report = Report.objects.create(title="R", year=2026, status=ReportStatus.PUBLISHED)
        self.assertEqual(report.published_on, timezone.localdate())
        self.assertFalse(report.is_pending)
        report.status = ReportStatus.RETURNED
        report.save()
        self.assertIsNone(report.published_on)

    def test_the_workflow_steps(self):
        report = Report(title="R", year=2026, status=ReportStatus.FOR_REVIEW)
        states = [step["state"] for step in report.workflow]
        self.assertEqual(states, ["done", "done", "current", "upcoming", "upcoming"])
        report.status = ReportStatus.PUBLISHED
        self.assertTrue(all(step["state"] == "done" for step in report.workflow))
        report.status = ReportStatus.RETURNED
        self.assertEqual(report.workflow[0]["state"], "cancelled")


class ReportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="staff", password="pw", role=Role.LGMED_STAFF)
        cls.encoder = User.objects.create_user(username="encoder", password="pw", role=Role.ENCODER)
        cls.viewer = User.objects.create_user(username="viewer", password="pw", role=Role.VIEWER)

    def setUp(self):
        import shutil
        import tempfile

        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def test_an_encoder_cannot_approve_or_publish(self):
        self.client.force_login(self.encoder)
        for status in (ReportStatus.APPROVED, ReportStatus.PUBLISHED):
            self.client.post(reverse("reports:create"), report_post(status=status, title=status))
            self.assertFalse(Report.objects.filter(title=status).exists(), status)
        self.client.post(reverse("reports:create"), report_post())
        self.assertTrue(Report.objects.filter(title="Q3 SGLG monitoring report").exists())

    def test_an_approver_publishes(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("reports:create"), report_post(status=ReportStatus.PUBLISHED))
        report = Report.objects.get(title="Q3 SGLG monitoring report")
        self.assertEqual(report.status, ReportStatus.PUBLISHED)
        self.assertEqual(report.published_on, timezone.localdate())

    def test_a_disguised_file_is_refused(self):
        self.client.force_login(self.encoder)
        response = self.client.post(reverse("reports:create"), report_post(
            file=SimpleUploadedFile("report.pdf", b"<html><script>alert(1)</script>"),
        ))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Report.objects.exists())

    def test_a_genuine_file_is_kept(self):
        self.client.force_login(self.encoder)
        self.client.post(reverse("reports:create"), report_post(
            file=SimpleUploadedFile("report.pdf", b"%PDF-1.7\n%..."),
        ))
        report = Report.objects.get()
        self.assertTrue(report.file.name.startswith("reports/2026/"))

    def test_a_viewer_reads_but_cannot_add(self):
        Report.objects.create(title="Annual report", year=2025, status=ReportStatus.PUBLISHED)
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("reports:list")), "Annual report")
        self.assertEqual(self.client.post(reverse("reports:create"), report_post()).status_code, 403)

    def test_the_list_summary_and_year_filter(self):
        Report.objects.create(title="Old", year=2024, status=ReportStatus.PUBLISHED)
        Report.objects.create(title="Pending", year=2026, status=ReportStatus.FOR_REVIEW)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("reports:list"), {"year": 2026})
        self.assertEqual(response.context["summary"]["pending"], 1)
        self.assertEqual(response.context["summary"]["published"], 1)
        self.assertContains(response, "Pending")
        self.assertNotContains(response, ">Old<")
