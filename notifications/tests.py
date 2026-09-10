"""
Tests for notifications.

A notification system earns its place only if it is trustworthy: it must tell
the right people, not tell them twice, stop telling them once the work is done,
and never show one person another person's queue.
"""

import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from documents.models import Document, DocumentStatus, DocumentType
from lgus.models import LGU, LGUType, Province
from monitoring.models import MonitoringActivity, MonitoringStatus
from notifications.models import Category, Level, Notification
from notifications.service import refresh_standing_notices
from reports.models import Report, ReportPeriod, ReportStatus


class NotificationAudienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )
        cls.retired = User.objects.create_user(
            username="retired", password="pw", role=Role.ADMIN, is_active=False
        )

    def submit_report(self):
        return Report.objects.create(
            title="Quarterly Report",
            period=ReportPeriod.QUARTERLY,
            year=2026,
            status=ReportStatus.SUBMITTED,
        )

    def test_a_submitted_report_notifies_those_who_can_approve(self):
        Notification.objects.all().delete()
        self.submit_report()

        notified = set(
            Notification.objects.values_list("recipient__username", flat=True)
        )
        self.assertEqual(notified, {"admin", "staff"})

    def test_a_deactivated_account_is_not_notified(self):
        Notification.objects.all().delete()
        self.submit_report()
        self.assertFalse(
            Notification.objects.filter(recipient=self.retired).exists()
        )

    def test_the_person_who_acted_is_not_told_about_their_own_action(self):
        self.client.force_login(self.staff)
        Notification.objects.all().delete()

        self.client.post(
            reverse("reports:create"),
            {
                "title": "Report I submitted myself",
                "period": ReportPeriod.QUARTERLY,
                "year": 2026,
                "summary": "",
                "prepared_by": "",
                "status": ReportStatus.SUBMITTED,
                "review_remarks": "",
                "reference_number": "",
            },
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.staff).exists()
        )
        self.assertTrue(Notification.objects.filter(recipient=self.admin).exists())


class NotificationLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )
        cls.province = Province.objects.create(name="Agusan del Norte")
        cls.lgu = LGU.objects.create(
            name="Cabadbaran City", lgu_type=LGUType.CITY, province=cls.province
        )

    def test_a_standing_condition_is_not_re_notified_on_every_run(self):
        """Three weeks overdue must not mean twenty-one notifications."""
        MonitoringActivity.objects.create(
            title="Overdue follow-up",
            lgu=self.lgu,
            monitoring_date=timezone.localdate() - datetime.timedelta(days=40),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.FOR_REVIEW,
            follow_up_date=timezone.localdate() - datetime.timedelta(days=21),
        )
        Notification.objects.all().delete()

        for _ in range(3):
            refresh_standing_notices()

        self.assertEqual(
            Notification.objects.filter(
                recipient=self.admin, category=Category.OVERDUE
            ).count(),
            1,
        )

    def test_a_long_overdue_follow_up_is_raised_as_urgent(self):
        MonitoringActivity.objects.create(
            title="Very overdue",
            lgu=self.lgu,
            monitoring_date=timezone.localdate() - datetime.timedelta(days=60),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.FOR_REVIEW,
            follow_up_date=timezone.localdate() - datetime.timedelta(days=30),
        )
        Notification.objects.all().delete()
        refresh_standing_notices()

        notification = Notification.objects.get(
            recipient=self.admin, category=Category.OVERDUE
        )
        self.assertEqual(notification.level, Level.URGENT)

    def test_a_notice_is_withdrawn_once_the_work_is_done(self):
        activity = MonitoringActivity.objects.create(
            title="Will be completed",
            lgu=self.lgu,
            monitoring_date=timezone.localdate() - datetime.timedelta(days=40),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.FOR_REVIEW,
            follow_up_date=timezone.localdate() - datetime.timedelta(days=5),
        )
        refresh_standing_notices()
        self.assertTrue(
            Notification.objects.for_user(self.admin).unread().exists()
        )

        activity.status = MonitoringStatus.COMPLETED
        activity.save()
        refresh_standing_notices()

        self.assertFalse(
            Notification.objects.for_user(self.admin).unread().exists()
        )

    def test_approving_a_report_withdraws_the_review_notice(self):
        report = Report.objects.create(
            title="Quarterly Report",
            period=ReportPeriod.QUARTERLY,
            year=2026,
            status=ReportStatus.FOR_REVIEW,
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.admin, category=Category.REVIEW
            ).unread().exists()
        )

        report.status = ReportStatus.APPROVED
        report.save()

        self.assertFalse(
            Notification.objects.filter(
                recipient=self.admin, category=Category.REVIEW
            ).unread().exists()
        )

    def test_a_document_review_notice_is_raised_and_then_withdrawn(self):
        """
        Documents are no longer driven by a signal on the status column.

        Every move goes through `documents.workflow`, which raises the notice
        for that move; the standing sweep then withdraws it once the document
        is no longer waiting on anyone.
        """
        from documents import workflow as documents_workflow

        encoder = User.objects.create_user(
            username="doc-encoder", password="pw", role=Role.ENCODER
        )
        approver = User.objects.create_user(
            username="doc-approver", password="pw", role=Role.LGMED_STAFF
        )
        document_type = DocumentType.objects.create(name="Memorandum")
        document = Document.objects.create(
            title="Memorandum on compliance",
            document_type=document_type,
            year=2026,
            owner=encoder,
            file="documents/2026/x.pdf",
            status=DocumentStatus.DRAFT,
        )
        Notification.objects.all().delete()

        documents_workflow.submit_for_review(document, encoder)
        self.assertTrue(
            Notification.objects.filter(
                dedupe_key=f"documents:review:{document.pk}"
            ).unread().exists()
        )

        documents_workflow.review(document, self.admin, notes="Noted.")
        documents_workflow.assign(document, self.admin, assignee=encoder)
        documents_workflow.start_processing(document, encoder)
        documents_workflow.submit_for_approval(document, encoder)
        documents_workflow.complete(document, approver)

        self.assertFalse(
            Notification.objects.filter(
                dedupe_key=f"documents:review:{document.pk}"
            ).unread().exists()
        )

    def test_a_saved_record_whose_status_did_not_change_raises_nothing(self):
        report = Report.objects.create(
            title="Quarterly Report",
            period=ReportPeriod.QUARTERLY,
            year=2026,
            status=ReportStatus.FOR_REVIEW,
        )
        Notification.objects.all().delete()

        report.title = "Quarterly Report (revised title)"
        report.save()

        self.assertEqual(Notification.objects.count(), 0)


class NotificationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mine = User.objects.create_user(
            username="mine", password="pw", role=Role.LGMED_STAFF
        )
        cls.theirs = User.objects.create_user(
            username="theirs", password="pw", role=Role.LGMED_STAFF
        )

    def make(self, recipient, **kwargs):
        return Notification.objects.create(
            recipient=recipient,
            title=kwargs.pop("title", "Something to do"),
            url=kwargs.pop("url", "/app/reports/"),
            **kwargs,
        )

    def test_the_list_shows_only_your_own(self):
        self.make(self.mine, title="Mine")
        self.make(self.theirs, title="Theirs")

        self.client.force_login(self.mine)
        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

    def test_you_cannot_open_someone_elses_notification(self):
        other = self.make(self.theirs)
        self.client.force_login(self.mine)
        response = self.client.get(reverse("notifications:open", args=[other.pk]))
        self.assertEqual(response.status_code, 404)
        other.refresh_from_db()
        self.assertIsNone(other.read_at)

    def test_opening_marks_read_and_redirects_to_the_work(self):
        notification = self.make(self.mine, url="/app/reports/")
        self.client.force_login(self.mine)

        response = self.client.get(
            reverse("notifications:open", args=[notification.pk])
        )
        self.assertRedirects(
            response, "/app/reports/", fetch_redirect_response=False
        )
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_mark_all_read_clears_the_unread_count(self):
        for index in range(3):
            self.make(self.mine, title=f"Item {index}")
        self.client.force_login(self.mine)

        self.client.post(reverse("notifications:read_all"))
        self.assertEqual(
            Notification.objects.for_user(self.mine).unread().count(), 0
        )

    def test_mark_all_read_does_not_touch_another_persons_queue(self):
        self.make(self.theirs)
        self.client.force_login(self.mine)
        self.client.post(reverse("notifications:read_all"))
        self.assertEqual(
            Notification.objects.for_user(self.theirs).unread().count(), 1
        )

    def test_dismissing_removes_it_from_the_list_without_deleting_it(self):
        notification = self.make(self.mine)
        self.client.force_login(self.mine)

        self.client.post(reverse("notifications:dismiss", args=[notification.pk]))
        notification.refresh_from_db()
        self.assertIsNotNone(notification.dismissed_at)
        self.assertFalse(
            Notification.objects.for_user(self.mine).visible().exists()
        )

    def test_the_header_bell_reports_the_users_own_unread_count(self):
        for index in range(4):
            self.make(self.mine, title=f"Item {index}")
        self.make(self.theirs)

        self.client.force_login(self.mine)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.context["unread_notifications"], 4)

    def test_the_bell_is_empty_for_a_user_with_nothing_waiting(self):
        self.client.force_login(self.mine)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.context["unread_notifications"], 0)
        self.assertContains(response, "Nothing needs your attention")
