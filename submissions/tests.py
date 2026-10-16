"""
Monthly Submissions: the staff upload, the Chief's deadline, the reminders.

Each scenario in the module brief has a test here, named for it. Emails go to
Django's in-memory outbox (the test runner's default), files to a temporary
protected root, so a run touches neither the mail server nor the real folder.
"""

import io
import shutil
import smtplib
import tempfile
import threading
import zipfile
from datetime import datetime, time, timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail.backends.base import BaseEmailBackend
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from core.testing import close_response
from notifications.models import Notification

from . import notify, services
from .models import (
    MANILA,
    AuditAction,
    EmailStatus,
    MonthlyStaffSubmission,
    MonthlySubmissionAuditLog,
    MonthlySubmissionNotification,
    MonthlySubmissionSchedule,
    NotificationType,
)
from .status import COMPLETED, NOT_SUBMITTED, OVERDUE, PARTIAL, standing

TEST_PROTECTED_ROOT = tempfile.mkdtemp(prefix="lgmed-imms-test-submissions-")


def pdf(name="report.pdf", body=b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def office(name, main="word/document.xml", extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr(main, "<document/>")
        for part, content in (extra or {}).items():
            package.writestr(part, content)
    return SimpleUploadedFile(name, buffer.getvalue())


class FailingBackend(BaseEmailBackend):
    """A mail server that is down."""

    def send_messages(self, messages):
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")


def make_schedule(days=10, month=None, year=None, chief=None, **extra):
    now = timezone.now()
    local = now.astimezone(MANILA)
    return MonthlySubmissionSchedule.objects.create(
        reporting_year=year or local.year,
        reporting_month=month or local.month,
        deadline=now + timedelta(days=days),
        deadline_set_at=extra.pop("deadline_set_at", now - timedelta(days=30)),
        created_by=chief,
        **extra,
    )


@override_settings(PROTECTED_MEDIA_ROOT=TEST_PROTECTED_ROOT)
class SubmissionTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_PROTECTED_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN, first_name="Divina",
            last_name="Chief", email="chief@example.gov.ph",
        )
        cls.juan = User.objects.create_user(
            username="juan", password="pw", role=Role.LGMED_STAFF,
            first_name="Juan", last_name="Dela Cruz", email="juan@example.gov.ph",
        )
        cls.maria = User.objects.create_user(
            username="maria", password="pw", role=Role.ENCODER,
            first_name="Maria", last_name="Santos", email="maria@example.gov.ph",
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER,
        )

    # The module notifies people once its transaction commits. A TestCase
    # never commits, so each action runs its on-commit work explicitly.

    def upload_as(self, user, schedule, kind, upload, ajax=False):
        self.client.force_login(user)
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse("submissions:upload", args=[schedule.pk]),
                {"kind": kind, "file": upload}, **headers,
            )

    def upload(self, user, schedule, kind, upload):
        with self.captureOnCommitCallbacks(execute=True):
            return services.upload(user, schedule, kind, upload)

    def post(self, url, data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url, data)


# ---------------------------------------------------------------------------
# Scenarios 1-5: uploading
# ---------------------------------------------------------------------------


class UploadTests(SubmissionTestCase):
    def test_01_mmia_only_is_incomplete(self):
        schedule = make_schedule()
        response = self.upload_as(self.juan, schedule, "mmia", pdf("mmia.pdf"), ajax=True)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], PARTIAL)
        self.assertIn("Incomplete Submission", data["html"]["summary"])

        submission = MonthlyStaffSubmission.objects.get(staff=self.juan)
        self.assertTrue(submission.has("mmia"))
        self.assertFalse(submission.has("dtr"))
        self.assertIsNone(submission.completed_at)
        self.assertEqual(standing(schedule, submission).missing, ["dtr"])
        notice = Notification.objects.get(recipient=self.juan, dedupe_key__endswith=":partial")
        self.assertIn("Your MMIA has been submitted. Your DTR is still pending.", notice.message)

    def test_02_dtr_only_is_incomplete(self):
        schedule = make_schedule()
        self.upload_as(self.juan, schedule, "dtr", office("dtr.xlsx", main="xl/workbook.xml"))
        submission = MonthlyStaffSubmission.objects.get(staff=self.juan)
        self.assertEqual(standing(schedule, submission).status, PARTIAL)
        self.assertEqual(standing(schedule, submission).missing, ["mmia"])

    def test_03_both_documents_complete_the_month(self):
        schedule = make_schedule()
        self.upload_as(self.juan, schedule, "mmia", office("mmia.docx"))
        response = self.upload_as(self.juan, schedule, "dtr", pdf("dtr.pdf"), ajax=True)
        self.assertTrue(response.json()["completed"])

        submission = MonthlyStaffSubmission.objects.get(staff=self.juan)
        self.assertIsNotNone(submission.completed_at)
        self.assertEqual(standing(schedule, submission).status, COMPLETED)
        self.assertTrue(MonthlySubmissionAuditLog.objects.filter(
            action=AuditAction.COMPLETED, staff=self.juan).exists())

        # Confirmation email to the staff member; the Chief is told in the
        # system only.
        notify.dispatch()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].subject,
            "LGMED-iMMS | Monthly Submission Successfully Completed",
        )
        self.assertEqual(mail.outbox[0].to, ["juan@example.gov.ph"])
        self.assertIn("MMIA: Submitted", mail.outbox[0].body)
        self.assertIn("DTR: Submitted", mail.outbox[0].body)
        self.assertTrue(Notification.objects.filter(
            recipient=self.chief, title__contains="completed").exists())
        # The "DTR still pending" notice is withdrawn once it no longer holds.
        self.assertFalse(Notification.objects.filter(
            recipient=self.juan, dedupe_key__endswith=":partial",
            dismissed_at__isnull=True).exists())

    def test_04_replacing_a_document_before_the_deadline(self):
        schedule = make_schedule()
        self.upload_as(self.juan, schedule, "mmia", pdf("first.pdf"))
        submission = MonthlyStaffSubmission.objects.get(staff=self.juan)
        first_name = submission.mmia_file.name
        storage = submission.mmia_file.storage
        self.assertTrue(storage.exists(first_name))

        self.upload_as(self.juan, schedule, "mmia", pdf("second.pdf"))
        submission.refresh_from_db()
        self.assertEqual(submission.mmia_original_name, "second.pdf")
        self.assertNotEqual(submission.mmia_file.name, first_name)
        self.assertFalse(storage.exists(first_name), "the superseded file is removed")
        self.assertTrue(MonthlySubmissionAuditLog.objects.filter(
            action=AuditAction.REPLACED, staff=self.juan).exists())

    def test_05_upload_after_the_deadline_is_refused(self):
        schedule = make_schedule(days=-1)
        response = self.upload_as(self.juan, schedule, "mmia", pdf(), ajax=True)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["closed"])
        self.assertFalse(MonthlyStaffSubmission.objects.filter(staff=self.juan).exists())
        self.assertTrue(MonthlySubmissionAuditLog.objects.filter(
            action=AuditAction.UPLOAD_REFUSED, staff=self.juan).exists())

        # The page says so, and offers no upload form.
        response = self.client.get(reverse("submissions:home") + f"?period={schedule.pk}")
        self.assertContains(response, "Submission Deadline Has Passed")
        self.assertNotContains(response, "data-upload-form")

    def test_plain_form_post_redirects_with_a_message(self):
        schedule = make_schedule()
        response = self.upload_as(self.juan, schedule, "mmia", pdf())
        self.assertRedirects(response, reverse("submissions:home") + f"?period={schedule.pk}")


# ---------------------------------------------------------------------------
# Scenarios 6-7: the Chief's deadline
# ---------------------------------------------------------------------------


class DeadlineTests(SubmissionTestCase):
    def deadline_form(self, when, **overrides):
        local = when.astimezone(MANILA)
        data = {
            "reporting_month": local.month,
            "reporting_year": local.year,
            "deadline_date": local.date().isoformat(),
            "deadline_time": "17:00",
            "announcement": "Submit on or before the deadline.",
        }
        data.update(overrides)
        return data

    def test_06_chief_sets_a_deadline_and_staff_are_told(self):
        self.client.force_login(self.chief)
        when = timezone.now() + timedelta(days=12)
        response = self.post(
            reverse("submissions:schedule_create"), self.deadline_form(when)
        )
        self.assertEqual(response.status_code, 302)
        schedule = MonthlySubmissionSchedule.objects.get()
        local = schedule.deadline_local
        self.assertEqual((local.hour, local.minute), (17, 0))
        self.assertEqual(str(local.tzinfo), "Asia/Manila")
        self.assertTrue(MonthlySubmissionAuditLog.objects.filter(
            action=AuditAction.SCHEDULE_CREATED).exists())

        # Bell notices at once; emails queued, then sent.
        for person in (self.juan, self.maria):
            self.assertTrue(Notification.objects.filter(
                recipient=person, title__contains="deadline set").exists())
        self.assertEqual(MonthlySubmissionNotification.objects.filter(
            notification_type=NotificationType.ANNOUNCEMENT).count(), 2)
        notify.dispatch()
        self.assertEqual(len(mail.outbox), 2)
        message = mail.outbox[0]
        self.assertEqual(message.subject, "LGMED-iMMS | Monthly MMIA and DTR Submission Reminder")
        self.assertIn("Dear LGMED Personnel,", message.body)
        self.assertIn("1. Monthly Monitoring Individual Accomplishments (MMIA)", message.body)
        self.assertIn("at 5:00 PM", message.body)
        self.assertIn(f"?period={schedule.pk}", message.body)
        self.assertIn("This is an automated system-generated notification.", message.body)
        self.assertNotIn(self.chief.email, [m.to[0] for m in mail.outbox])

    def test_only_one_schedule_per_month(self):
        self.client.force_login(self.chief)
        when = timezone.now() + timedelta(days=12)
        self.client.post(reverse("submissions:schedule_create"), self.deadline_form(when))
        response = self.client.post(
            reverse("submissions:schedule_create"), self.deadline_form(when)
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already set for that reporting month")
        self.assertEqual(MonthlySubmissionSchedule.objects.count(), 1)

    def test_deadline_must_be_in_the_future(self):
        self.client.force_login(self.chief)
        response = self.client.post(
            reverse("submissions:schedule_create"),
            self.deadline_form(timezone.now() - timedelta(days=2)),
        )
        self.assertContains(response, "later than the present time")
        self.assertFalse(MonthlySubmissionSchedule.objects.exists())

    def test_staff_cannot_set_or_change_deadlines(self):
        schedule = make_schedule()
        self.client.force_login(self.juan)
        when = timezone.now() + timedelta(days=12)
        self.assertEqual(self.client.post(
            reverse("submissions:schedule_create"), self.deadline_form(when)
        ).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("submissions:schedule_update", args=[schedule.pk]),
            self.deadline_form(when),
        ).status_code, 403)
        self.assertEqual(self.client.get(reverse("submissions:schedules")).status_code, 403)

    def test_07_chief_extends_a_passed_deadline(self):
        schedule = make_schedule(days=-1)
        MonthlyStaffSubmission.objects.create(
            staff=self.maria, schedule=schedule, completed_at=timezone.now(),
            mmia_file="x/mmia.pdf", dtr_file="x/dtr.pdf",
        )
        old_deadline = schedule.deadline

        self.client.force_login(self.chief)
        new = timezone.now() + timedelta(days=3)
        response = self.post(
            reverse("submissions:schedule_update", args=[schedule.pk]),
            self.deadline_form(new, reporting_month=99),  # ignored: month is fixed
        )
        self.assertRedirects(response, reverse("submissions:schedules"))
        schedule.refresh_from_db()
        self.assertGreater(schedule.deadline, old_deadline)
        self.assertTrue(schedule.is_open())
        entry = MonthlySubmissionAuditLog.objects.get(action=AuditAction.DEADLINE_EXTENDED)
        self.assertIn("moved from", entry.details)

        # Only the staff member still missing documents is told.
        notify.dispatch()
        self.assertEqual([m.to for m in mail.outbox], [["juan@example.gov.ph"]])
        self.assertEqual(mail.outbox[0].subject, "LGMED-iMMS | Monthly Submission Deadline Extended")

        # And uploads are open again.
        response = self.upload_as(self.juan, schedule, "mmia", pdf(), ajax=True)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Scenarios 8-9, 13-14: reminders
# ---------------------------------------------------------------------------


class ReminderTests(SubmissionTestCase):
    def at(self, schedule, days_before, hour=9):
        day = schedule.deadline_local.date() - timedelta(days=days_before)
        return datetime.combine(day, time(hour, 0), tzinfo=MANILA)

    def test_08_pending_staff_are_reminded_three_days_before(self):
        schedule = make_schedule(days=10)
        self.upload(self.juan, schedule, "mmia", pdf())
        mail.outbox.clear()
        MonthlySubmissionNotification.objects.all().delete()

        moment = self.at(schedule, 3)
        summary = notify.queue_scheduled(moment)
        self.assertEqual(summary["reminders"], 2)
        notify.dispatch(at=moment)
        by_person = {m.to[0]: m for m in mail.outbox}
        juan = by_person["juan@example.gov.ph"]
        self.assertIn("Due in 3 Days", juan.subject)
        self.assertIn("MMIA): Submitted", juan.body)
        self.assertIn("DTR): Not Submitted", juan.body)
        self.assertIn(
            "Your Daily Time Record (DTR) is still pending. Please upload the "
            "document before the prescribed deadline.", juan.body,
        )
        self.assertTrue(Notification.objects.filter(
            recipient=self.maria, message__contains="3 days remaining").exists())

        # Running again the same day sends nothing new.
        self.assertEqual(notify.queue_scheduled(moment)["reminders"], 0)

    def test_reminders_wait_for_office_hours(self):
        schedule = make_schedule(days=10)
        self.assertEqual(notify.queue_scheduled(self.at(schedule, 3, hour=2))["reminders"], 0)

    def test_no_reminder_that_the_announcement_already_covers(self):
        schedule = make_schedule(days=2, deadline_set_at=timezone.now())
        self.assertEqual(notify.queue_scheduled(self.at(schedule, 2))["reminders"], 0)
        # The 1-day reminder still follows.
        self.assertEqual(notify.queue_scheduled(self.at(schedule, 1))["reminders"], 2)

    def test_09_completed_staff_are_not_reminded(self):
        schedule = make_schedule(days=10)
        self.upload(self.juan, schedule, "mmia", pdf())
        self.upload(self.juan, schedule, "dtr", pdf())
        moment = self.at(schedule, 7)
        notify.queue_scheduled(moment)
        reminded = set(MonthlySubmissionNotification.objects.filter(
            notification_type=NotificationType.REMINDER
        ).values_list("recipient__username", flat=True))
        self.assertEqual(reminded, {"maria"})

    def test_reminder_queued_then_completed_is_not_sent(self):
        schedule = make_schedule(days=10)
        moment = self.at(schedule, 3)
        notify.queue_scheduled(moment)
        self.upload(self.maria, schedule, "mmia", pdf())
        self.upload(self.maria, schedule, "dtr", pdf())
        notify.dispatch(at=moment)
        maria = MonthlySubmissionNotification.objects.get(
            recipient=self.maria, notification_type=NotificationType.REMINDER)
        self.assertEqual(maria.email_status, EmailStatus.SKIPPED)

    def test_overdue_notice_after_the_deadline(self):
        schedule = make_schedule(days=-1)
        moment = timezone.now().astimezone(MANILA).replace(hour=10)
        summary = notify.queue_scheduled(moment)
        self.assertEqual(summary["overdue"], 2)
        notify.dispatch(at=moment)
        self.assertEqual(mail.outbox[0].subject, "LGMED-iMMS | Overdue Monthly MMIA and DTR Submission")
        self.assertIn("Outstanding:", mail.outbox[0].body)
        self.assertTrue(Notification.objects.filter(
            recipient=self.juan,
            message__contains="contact your Division Chief").exists())
        self.assertEqual(notify.queue_scheduled(moment)["overdue"], 0)

    def test_14_mail_server_down_then_retried(self):
        schedule = make_schedule(days=10)
        with override_settings(
            EMAIL_BACKEND="submissions.tests.FailingBackend",
        ):
            self.upload(self.juan, schedule, "mmia", pdf())
            self.upload(self.juan, schedule, "dtr", pdf())
            result = notify.dispatch()
        self.assertEqual(result["failed"], 1)
        # The upload itself stands.
        self.assertIsNotNone(
            MonthlyStaffSubmission.objects.get(staff=self.juan).completed_at)
        notice = MonthlySubmissionNotification.objects.get(
            notification_type=NotificationType.COMPLETED)
        self.assertEqual(notice.email_status, EmailStatus.FAILED)
        self.assertEqual(notice.attempts, 1)
        self.assertIn("Connection unexpectedly closed", notice.last_error)

        # Not retried before the retry interval...
        self.assertEqual(notify.dispatch()["sent"], 0)
        # ...and sent once it has passed and the server is back.
        later = timezone.now() + timedelta(minutes=11)
        self.assertEqual(notify.dispatch(at=later)["sent"], 1)
        notice.refresh_from_db()
        self.assertEqual(notice.email_status, EmailStatus.SENT)
        self.assertEqual(notice.attempts, 2)

    def test_the_command_runs(self):
        from django.core.management import call_command

        make_schedule(days=-1)
        out = io.StringIO()
        call_command("send_submission_reminders", stdout=out)
        self.assertIn("Emails sent", out.getvalue())


@override_settings(PROTECTED_MEDIA_ROOT=TEST_PROTECTED_ROOT)
class ConcurrentReminderTests(TransactionTestCase):
    """Scenario 13: two reminder jobs at once send each email exactly once."""

    def test_13_overlapping_jobs_do_not_duplicate(self):
        staff = [
            User.objects.create_user(
                username=f"staff{i}", password="pw", role=Role.LGMED_STAFF,
                email=f"staff{i}@example.gov.ph",
            )
            for i in range(6)
        ]
        schedule = make_schedule(days=10)
        day = schedule.deadline_local.date() - timedelta(days=3)
        moment = datetime.combine(day, time(9, 0), tzinfo=MANILA)

        barrier = threading.Barrier(3)
        errors = []

        def job():
            try:
                barrier.wait()
                notify.queue_scheduled(moment)
                notify.dispatch(at=moment)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=job) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        recipients = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(recipients, sorted(person.email for person in staff))
        self.assertEqual(MonthlySubmissionNotification.objects.count(), len(staff))


# ---------------------------------------------------------------------------
# Scenarios 10-12: who sees what
# ---------------------------------------------------------------------------


class AccessTests(SubmissionTestCase):
    def test_10_chief_monitors_every_staff_member(self):
        schedule = make_schedule()
        self.upload(self.juan, schedule, "mmia", pdf())
        self.upload(self.juan, schedule, "dtr", pdf())
        self.upload(self.maria, schedule, "mmia", pdf())

        self.client.force_login(self.chief)
        response = self.client.get(reverse("submissions:home"))
        self.assertContains(response, "Monthly Staff Submission Monitoring")
        self.assertContains(response, "Juan Dela Cruz")
        self.assertContains(response, "Maria Santos")
        summary = response.context["summary"]
        self.assertEqual(
            (summary["total"], summary["completed"], summary["partial"],
             summary["not_submitted"], summary["overdue"]),
            (2, 1, 1, 0, 0),
        )
        # The Chief opens a staff member's file.
        submission = MonthlyStaffSubmission.objects.get(staff=self.juan)
        response = self.client.get(reverse("submissions:file", args=[submission.pk, "dtr"]))
        self.assertEqual(response.status_code, 200)
        close_response(response)
        self.assertTrue(MonthlySubmissionAuditLog.objects.filter(
            action=AuditAction.DOWNLOADED, user=self.chief, staff=self.juan).exists())
        # And the review page.
        response = self.client.get(reverse("submissions:review", args=[schedule.pk, self.maria.pk]))
        self.assertContains(response, "Daily Time Record")

    def test_filters_search_and_status(self):
        schedule = make_schedule()
        self.upload(self.juan, schedule, "mmia", pdf())
        self.client.force_login(self.chief)
        response = self.client.get(reverse("submissions:home"), {"q": "maria"})
        rows = response.context["rows"]
        self.assertEqual([row.staff for row in rows], [self.maria])
        response = self.client.get(reverse("submissions:home"), {"status": PARTIAL})
        self.assertEqual([row.staff for row in response.context["rows"]], [self.juan])

    def test_11_staff_cannot_open_another_staff_members_file(self):
        schedule = make_schedule()
        self.upload(self.juan, schedule, "mmia", pdf())
        submission = MonthlyStaffSubmission.objects.get(staff=self.juan)
        self.client.force_login(self.maria)
        for name in ("submissions:file", "submissions:file_view"):
            response = self.client.get(reverse(name, args=[submission.pk, "mmia"]))
            self.assertEqual(response.status_code, 403)
        for name in ("submissions:review",):
            self.assertEqual(self.client.get(
                reverse(name, args=[schedule.pk, self.juan.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("submissions:export")).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("submissions:remind"), {"selected": [f"{schedule.pk}:{self.juan.pk}"]}
        ).status_code, 403)
        # The owner can.
        self.client.force_login(self.juan)
        response = self.client.get(reverse("submissions:file", args=[submission.pk, "mmia"]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("monthly_submissions/", response["Content-Disposition"])
        close_response(response)

    def test_signed_out_and_other_roles_are_refused(self):
        response = self.client.get(reverse("submissions:home"))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("submissions:home")).status_code, 403)

    def test_sidebar_offers_the_module(self):
        make_schedule()
        for person in (self.juan, self.chief):
            self.client.force_login(person)
            response = self.client.get(reverse("core:dashboard"))
            self.assertContains(response, "Monthly Submissions")
        self.client.force_login(self.viewer)
        self.assertNotContains(self.client.get(reverse("core:dashboard")), "Monthly Submissions")

    def test_12_previous_months_stay_on_record(self):
        old = make_schedule(days=-40, month=1, year=2026)
        MonthlyStaffSubmission.objects.create(staff=self.juan, schedule=old)
        submission = MonthlyStaffSubmission.objects.get(staff=self.juan, schedule=old)
        submission.mmia_file.save("old.pdf", pdf("old.pdf"), save=False)
        submission.mmia_original_name = "old.pdf"
        submission.mmia_uploaded_at = timezone.now() - timedelta(days=41)
        submission.save()
        current = make_schedule(days=10)

        self.client.force_login(self.juan)
        response = self.client.get(reverse("submissions:home"))
        self.assertEqual(response.context["schedule"], current)
        self.assertContains(response, "Monthly Submission History")
        self.assertContains(response, "January 2026")
        history = {item["schedule"].pk: item for item in response.context["history"]}
        self.assertEqual(history[old.pk]["standing"].status, OVERDUE)
        self.assertEqual(history[current.pk]["standing"].status, NOT_SUBMITTED)
        response = self.client.get(reverse("submissions:file", args=[submission.pk, "mmia"]))
        self.assertEqual(response.status_code, 200)
        close_response(response)

    def test_chief_sends_a_reminder(self):
        schedule = make_schedule()
        self.upload(self.juan, schedule, "dtr", pdf())
        self.client.force_login(self.chief)
        response = self.client.post(reverse("submissions:remind"), {
            "selected": [f"{schedule.pk}:{self.juan.pk}"],
            "message": "Please upload today.",
        })
        self.assertEqual(response.status_code, 302)
        notify.dispatch()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Please upload today.", mail.outbox[0].body)
        self.assertIn("Your Monthly Monitoring Individual Accomplishments (MMIA) is still pending",
                      mail.outbox[0].body)
        self.assertTrue(MonthlySubmissionAuditLog.objects.filter(
            action=AuditAction.REMINDER_SENT, staff=self.juan).exists())

    def test_completed_staff_cannot_be_selected_for_a_reminder(self):
        schedule = make_schedule()
        self.upload(self.juan, schedule, "mmia", pdf())
        self.upload(self.juan, schedule, "dtr", pdf())
        self.client.force_login(self.chief)
        self.client.post(reverse("submissions:remind"),
                         {"selected": [f"{schedule.pk}:{self.juan.pk}"]})
        self.assertFalse(MonthlySubmissionNotification.objects.filter(
            notification_type=NotificationType.MANUAL_REMINDER).exists())

    def test_every_chief_page_renders(self):
        self.client.force_login(self.chief)
        # Before any deadline exists.
        response = self.client.get(reverse("submissions:home"))
        self.assertContains(response, "No submission deadline has been set")

        schedule = make_schedule(announcement="Submit on time.")
        closed = make_schedule(days=-20, month=1, year=2025)
        self.upload(self.juan, schedule, "mmia", pdf())
        pages = [
            reverse("submissions:home"),
            reverse("submissions:home") + "?year=&month=&status=partial&sort=-submitted",
            reverse("submissions:home") + "?year=2025&month=1",
            reverse("submissions:schedules"),
            reverse("submissions:schedule_update", args=[schedule.pk]),
            reverse("submissions:schedule_update", args=[closed.pk]),
            reverse("submissions:review", args=[schedule.pk, self.juan.pk]),
            reverse("submissions:review", args=[closed.pk, self.maria.pk]),
        ]
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get(reverse("submissions:schedule_update", args=[closed.pk]))
        self.assertContains(response, "Setting a later date extends it")

    def test_staff_page_without_any_deadline(self):
        self.client.force_login(self.juan)
        response = self.client.get(reverse("submissions:home"))
        self.assertContains(response, "No submission period has been opened yet")

    def test_compliance_report_export(self):
        schedule = make_schedule()
        self.upload(self.juan, schedule, "mmia", pdf())
        self.upload(self.juan, schedule, "dtr", pdf())
        self.client.force_login(self.chief)
        response = self.client.get(reverse("submissions:export"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        self.assertIn("Completion percentage,50%", body)
        self.assertIn("Juan Dela Cruz", body)


# ---------------------------------------------------------------------------
# Scenario 15: what is not accepted
# ---------------------------------------------------------------------------


class FileValidationTests(SubmissionTestCase):
    def assertRefused(self, upload, fragment):
        schedule = MonthlySubmissionSchedule.objects.first() or make_schedule()
        response = self.upload_as(self.juan, schedule, "mmia", upload, ajax=True)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(fragment, " ".join(response.json()["errors"]))
        self.assertFalse(MonthlyStaffSubmission.objects.filter(
            staff=self.juan, mmia_file__gt="").exists())

    def test_15_program_renamed_as_pdf(self):
        self.assertRefused(SimpleUploadedFile("mmia.pdf", b"MZ\x90\x00 program"),
                           "do not match")

    def test_web_page_renamed_as_pdf(self):
        self.assertRefused(SimpleUploadedFile("mmia.pdf", b"<html><script>"), "do not match")

    def test_unsupported_extension(self):
        self.assertRefused(SimpleUploadedFile("mmia.exe", b"MZ"), "Only PDF")
        self.assertRefused(SimpleUploadedFile("mmia.html", b"<html>"), "Only PDF")

    def test_pdf_with_javascript(self):
        self.assertRefused(
            pdf(body=b"%PDF-1.4\n<< /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>"),
            "scripts",
        )

    def test_docx_with_macros(self):
        self.assertRefused(
            office("mmia.docx", extra={"word/vbaProject.bin": "macro"}), "macros",
        )

    def test_xlsx_that_is_really_a_word_document(self):
        self.assertRefused(office("dtr.xlsx", main="word/document.xml"), "do not match")

    def test_empty_and_oversized_files(self):
        self.assertRefused(SimpleUploadedFile("mmia.pdf", b""), "empty")
        with override_settings(MONTHLY_SUBMISSION_MAX_UPLOAD_MB=1):
            self.assertRefused(pdf(body=b"%PDF-1.4" + b"0" * (1024 * 1024 + 1)), "1 MB")

    def test_filename_is_sanitised(self):
        schedule = make_schedule()
        self.upload_as(self.juan, schedule, "mmia", pdf('..\\..\\evil<name>.PDF'))
        submission = MonthlyStaffSubmission.objects.get(staff=self.juan)
        self.assertEqual(submission.mmia_original_name, "evilname.pdf")
        self.assertTrue(submission.mmia_file.name.startswith("monthly_submissions/"))
        self.assertNotIn("evil", submission.mmia_file.name)

    def test_only_mmia_and_dtr_slots_exist(self):
        schedule = make_schedule()
        response = self.upload_as(self.juan, schedule, "payslip", pdf(), ajax=True)
        self.assertEqual(response.status_code, 400)
