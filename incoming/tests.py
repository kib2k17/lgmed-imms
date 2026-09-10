"""
Tests for Incoming Monitoring.

The workflow rule is what these mostly assert: an encoder records a document
but cannot assign it, and the ways round that - posting to the assign URL
directly, editing a record after the Chief has acted on it - are refused by the
server rather than merely hidden from the page.
"""

import datetime

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from documents.models import DocumentType
from notifications.models import Notification

from . import workflow
from .models import (
    EventType,
    IncomingDocument,
    IncomingStatus,
    IncomingUpdate,
    Priority,
)


class IncomingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.document_type = DocumentType.objects.create(name="Memorandum")
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER,
            first_name="Elena", last_name="Reyes",
        )
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN,
            first_name="Divina", last_name="Cruz",
        )
        cls.focal = User.objects.create_user(
            username="focal", password="pw", role=Role.LGMED_STAFF,
            first_name="Mario", last_name="Salazar",
        )
        cls.other_focal = User.objects.create_user(
            username="focal2", password="pw", role=Role.ENCODER,
            first_name="Rosa", last_name="Antonio",
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )

    def make_document(self, **overrides):
        fields = {
            "docket_number": "2026-0001",
            "subject": "Request for validation of SGLG documentary requirements",
            "document_type": self.document_type,
            "date_received": timezone.localdate(),
            "source_office": "Office of the Regional Director",
            "created_by": self.encoder,
        }
        fields.update(overrides)
        document = IncomingDocument.objects.create(**fields)
        workflow.record_received(document, self.encoder)
        return document

    def assign_to_focal(self, document, **overrides):
        options = {
            "assignee": self.focal,
            "remarks": "Prepare the validation report.",
            "priority": Priority.HIGH,
            "due_date": timezone.localdate() + datetime.timedelta(days=5),
        }
        options.update(overrides)
        return workflow.assign(document, self.chief, **options)


class RecordingTests(IncomingTestCase):
    def test_a_recorded_document_starts_unassigned_and_awaiting_review(self):
        document = self.make_document()
        self.assertEqual(document.status, IncomingStatus.FOR_REVIEW)
        self.assertIsNone(document.assigned_to)
        self.assertFalse(document.is_reviewed)

    def test_the_encoders_form_has_no_way_to_name_a_focal_person(self):
        """The rule is in the shape of the form, not only in a permission check."""
        from .forms import IncomingDocumentForm

        fields = set(IncomingDocumentForm().fields)
        self.assertNotIn("assigned_to", fields)
        self.assertNotIn("status", fields)
        self.assertNotIn("due_date", fields)

    def test_recording_notifies_the_division_chief_and_nobody_else(self):
        document = self.make_document()
        recipients = set(
            Notification.objects.filter(
                dedupe_key=workflow.review_key(document)
            ).values_list("recipient__username", flat=True)
        )
        self.assertEqual(recipients, {"chief"})

    def test_an_encoder_may_record_through_the_interface(self):
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("incoming:create"),
            {
                "docket_number": "2026-0099",
                "subject": "Advisory on the conduct of barangay assemblies",
                "document_type": self.document_type.pk,
                "date_received": timezone.localdate().isoformat(),
                "source_office": "DILG Central Office",
                "initial_remarks": "Received at the records counter.",
            },
        )
        self.assertEqual(response.status_code, 302)
        document = IncomingDocument.objects.get(docket_number="2026-0099")
        self.assertEqual(document.status, IncomingStatus.FOR_REVIEW)
        self.assertIsNone(document.assigned_to)
        self.assertTrue(document.events.filter(event_type=EventType.RECORDED).exists())

    def test_a_document_cannot_be_recorded_as_received_in_the_future(self):
        from .forms import IncomingDocumentForm

        form = IncomingDocumentForm(
            {
                "docket_number": "2026-0100",
                "subject": "Future document",
                "document_type": self.document_type.pk,
                "date_received": (
                    timezone.localdate() + datetime.timedelta(days=1)
                ).isoformat(),
                "source_office": "Somewhere",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("date_received", form.errors)


class AssignmentTests(IncomingTestCase):
    def test_only_the_division_chief_may_assign(self):
        document = self.make_document()
        for user in (self.encoder, self.focal, self.viewer):
            with self.subTest(user=user.username):
                with self.assertRaises(PermissionDenied):
                    workflow.assign(document, user, assignee=self.focal)

    def test_an_encoder_posting_to_the_assign_url_is_refused(self):
        """Hiding the form is not the control - the server refuses the request."""
        document = self.make_document()
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("incoming:assign", args=[document.pk]),
            {"assigned_to": self.focal.pk, "priority": Priority.NORMAL},
        )
        self.assertEqual(response.status_code, 403)
        document.refresh_from_db()
        self.assertIsNone(document.assigned_to)

    def test_assigning_records_who_decided_and_when(self):
        document = self.assign_to_focal(self.make_document())
        document.refresh_from_db()
        self.assertEqual(document.status, IncomingStatus.ASSIGNED)
        self.assertEqual(document.assigned_to, self.focal)
        self.assertEqual(document.assigned_by, self.chief)
        self.assertIsNotNone(document.assigned_at)
        self.assertEqual(document.reviewed_by, self.chief)
        self.assertIsNotNone(document.reviewed_at)

    def test_assigning_notifies_the_focal_person(self):
        document = self.assign_to_focal(self.make_document())
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.focal, dedupe_key=workflow.assignment_key(document)
            ).exists()
        )

    def test_assigning_withdraws_the_chiefs_review_notice(self):
        document = self.make_document()
        key = workflow.review_key(document)
        self.assertTrue(Notification.objects.filter(dedupe_key=key).unread().exists())
        self.assign_to_focal(document)
        self.assertFalse(Notification.objects.filter(dedupe_key=key).unread().exists())

    def test_reassignment_is_recorded_as_such(self):
        document = self.assign_to_focal(self.make_document())
        workflow.assign(document, self.chief, assignee=self.other_focal)
        document.refresh_from_db()
        self.assertEqual(document.assigned_to, self.other_focal)
        self.assertTrue(document.events.filter(event_type=EventType.REASSIGNED).exists())

    def test_a_chief_may_review_without_assigning(self):
        document = self.make_document()
        workflow.review(document, self.chief, "Refer to the SGLG focal person.")
        document.refresh_from_db()
        self.assertTrue(document.is_reviewed)
        self.assertEqual(document.status, IncomingStatus.FOR_REVIEW)
        self.assertIsNone(document.assigned_to)


class FocalPersonTests(IncomingTestCase):
    def test_only_the_assigned_person_may_acknowledge(self):
        document = self.assign_to_focal(self.make_document())
        with self.assertRaises(PermissionDenied):
            workflow.acknowledge(document, self.other_focal)
        workflow.acknowledge(document, self.focal)
        document.refresh_from_db()
        self.assertEqual(document.status, IncomingStatus.ACKNOWLEDGED)
        self.assertIsNotNone(document.acknowledged_at)

    def test_an_update_moves_the_document_to_the_status_it_reports(self):
        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
        workflow.add_update(
            document,
            self.focal,
            IncomingUpdate(
                action_taken="Drafted the reply for the Chief's signature.",
                status=IncomingStatus.IN_PROGRESS,
            ),
        )
        document.refresh_from_db()
        self.assertEqual(document.status, IncomingStatus.IN_PROGRESS)
        self.assertEqual(document.updates.count(), 1)

    def test_completing_stamps_the_completion_time(self):
        document = self.assign_to_focal(self.make_document())
        workflow.add_update(
            document,
            self.focal,
            IncomingUpdate(
                action_taken="Reply transmitted.", status=IncomingStatus.COMPLETED
            ),
        )
        document.refresh_from_db()
        self.assertTrue(document.is_completed)
        self.assertIsNotNone(document.completed_at)
        self.assertTrue(document.events.filter(event_type=EventType.COMPLETED).exists())

    def test_a_completed_document_shows_every_stage_as_done(self):
        """The last stage is the end of the road, not the step being worked on."""
        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
        workflow.add_update(
            document,
            self.focal,
            IncomingUpdate(action_taken="Closed.", status=IncomingStatus.COMPLETED),
        )
        document.refresh_from_db()
        states = [stage["state"] for stage in document.workflow]
        self.assertEqual(states, ["done"] * 5)

    def test_an_unfinished_document_still_marks_its_current_stage(self):
        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
        states = [stage["state"] for stage in document.workflow]
        self.assertEqual(states, ["done", "done", "current", "upcoming", "upcoming"])

    def test_an_unassigned_person_cannot_post_an_update(self):
        document = self.assign_to_focal(self.make_document())
        self.client.force_login(self.other_focal)
        response = self.client.post(
            reverse("incoming:add_update", args=[document.pk]),
            {"action_taken": "Meddling.", "status": IncomingStatus.IN_PROGRESS},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(document.updates.count(), 0)

    def test_returning_sends_the_document_back_to_the_focal_person(self):
        document = self.assign_to_focal(self.make_document())
        workflow.add_update(
            document,
            self.focal,
            IncomingUpdate(action_taken="Done.", status=IncomingStatus.COMPLETED),
        )
        workflow.return_for_revision(document, self.chief, "The figures need checking.")
        document.refresh_from_db()
        self.assertEqual(document.status, IncomingStatus.RETURNED)
        self.assertIsNone(document.completed_at)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.focal, title__startswith="Returned for revision"
            ).exists()
        )


class EditingTests(IncomingTestCase):
    def test_an_encoder_may_amend_only_before_the_chief_has_acted(self):
        document = self.make_document()
        self.client.force_login(self.encoder)
        self.assertEqual(
            self.client.get(reverse("incoming:update", args=[document.pk])).status_code,
            200,
        )
        self.assign_to_focal(document)
        self.assertEqual(
            self.client.get(reverse("incoming:update", args=[document.pk])).status_code,
            403,
        )

    def test_the_chief_may_amend_an_assigned_record(self):
        document = self.assign_to_focal(self.make_document())
        self.client.force_login(self.chief)
        self.assertEqual(
            self.client.get(reverse("incoming:update", args=[document.pk])).status_code,
            200,
        )


class OverdueTests(IncomingTestCase):
    def test_a_document_past_its_due_date_reports_itself_overdue(self):
        document = self.assign_to_focal(
            self.make_document(),
            due_date=timezone.localdate() + datetime.timedelta(days=1),
        )
        IncomingDocument.objects.filter(pk=document.pk).update(
            due_date=timezone.localdate() - datetime.timedelta(days=3)
        )
        document.refresh_from_db()
        self.assertTrue(document.is_overdue)
        self.assertEqual(document.days_overdue, 3)
        self.assertEqual(document.display_status, "overdue")
        self.assertIn(document, IncomingDocument.objects.overdue())

    def test_a_completed_document_is_never_overdue(self):
        document = self.assign_to_focal(self.make_document())
        IncomingDocument.objects.filter(pk=document.pk).update(
            due_date=timezone.localdate() - datetime.timedelta(days=3)
        )
        document.refresh_from_db()
        workflow.add_update(
            document,
            self.focal,
            IncomingUpdate(action_taken="Done.", status=IncomingStatus.COMPLETED),
        )
        document.refresh_from_db()
        self.assertFalse(document.is_overdue)
        self.assertNotIn(document, IncomingDocument.objects.overdue())

    def test_standing_notices_raise_and_then_withdraw_the_overdue_condition(self):
        document = self.assign_to_focal(self.make_document())
        IncomingDocument.objects.filter(pk=document.pk).update(
            due_date=timezone.localdate() - datetime.timedelta(days=2)
        )
        workflow.refresh_standing_notices()
        key = workflow.overdue_key(document)
        self.assertTrue(Notification.objects.filter(dedupe_key=key).unread().exists())

        # Running again must not produce a second notice for the same condition.
        workflow.refresh_standing_notices()
        self.assertEqual(
            Notification.objects.filter(dedupe_key=key, recipient=self.focal).count(), 1
        )

        document.refresh_from_db()
        workflow.add_update(
            document,
            self.focal,
            IncomingUpdate(action_taken="Closed.", status=IncomingStatus.COMPLETED),
        )
        workflow.refresh_standing_notices()
        self.assertFalse(Notification.objects.filter(dedupe_key=key).unread().exists())


class ListAndPermissionTests(IncomingTestCase):
    def test_the_list_renders_for_every_signed_in_role(self):
        for user in (self.encoder, self.chief, self.focal, self.viewer):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertEqual(
                    self.client.get(reverse("incoming:list")).status_code, 200
                )

    def test_quick_views_filter_the_list(self):
        recorded = self.make_document()
        assigned = self.assign_to_focal(
            self.make_document(docket_number="2026-0002", subject="Second document")
        )
        self.client.force_login(self.chief)

        response = self.client.get(reverse("incoming:list"), {"view": "for_review"})
        rows = list(response.context["records"])
        self.assertIn(recorded, rows)
        self.assertNotIn(assigned, rows)

        response = self.client.get(reverse("incoming:list"), {"view": "unassigned"})
        self.assertNotIn(assigned, list(response.context["records"]))

    def test_the_focal_person_can_filter_to_their_own_assignments(self):
        mine = self.assign_to_focal(self.make_document())
        theirs = self.assign_to_focal(
            self.make_document(docket_number="2026-0003", subject="Someone else's"),
            assignee=self.other_focal,
        )
        self.client.force_login(self.focal)
        response = self.client.get(reverse("incoming:list"), {"view": "mine"})
        rows = list(response.context["records"])
        self.assertIn(mine, rows)
        self.assertNotIn(theirs, rows)

    def test_the_monitoring_dashboard_is_the_chiefs_alone(self):
        url = reverse("incoming:dashboard")
        self.client.force_login(self.encoder)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.chief)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_viewer_cannot_reach_the_reports(self):
        url = reverse("incoming:reports")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.encoder)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_the_detail_page_shows_the_trail(self):
        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
        self.client.force_login(self.chief)
        response = self.client.get(document.get_absolute_url())
        self.assertContains(response, "Received and recorded")
        self.assertContains(response, "Assigned to a focal person")
        self.assertContains(response, "Acknowledged by the focal person")


class ReportTests(IncomingTestCase):
    def test_every_report_builds_without_records(self):
        """
        An empty office must not produce a broken report.

        `by-status` is the exception that proves the point: it lists every
        status with a zero rather than nothing at all, which is the right
        answer to "how is the caseload distributed" when there is no caseload.
        """
        from . import reports

        for slug in reports.REPORTS:
            with self.subTest(report=slug):
                queryset, _applied, _sort = reports.filtered_queryset({})
                result = reports.get_report(slug)["build"](queryset)
                self.assertIn("headers", result)
                if slug == "by-status":
                    self.assertEqual(len(result["rows"]), len(IncomingStatus.choices))
                    self.assertTrue(all(row[1] == "0" for row in result["rows"]))
                else:
                    self.assertEqual(result["rows"], [])

    def test_the_export_carries_the_filtered_rows(self):
        self.assign_to_focal(self.make_document())
        self.make_document(docket_number="2026-0004", subject="Still for review")
        self.client.force_login(self.chief)
        response = self.client.get(
            reverse("incoming:reports"),
            {"report": "for-review", "export": "csv"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        self.assertIn("2026-0004", body)
        self.assertNotIn("2026-0001", body)

    def test_the_workload_report_counts_each_officers_documents(self):
        from . import reports

        self.assign_to_focal(self.make_document())
        self.assign_to_focal(
            self.make_document(docket_number="2026-0005", subject="Another"),
            assignee=self.other_focal,
        )
        queryset, _applied, _sort = reports.filtered_queryset({})
        result = reports.get_report("by-focal-person")["build"](queryset)
        people = {row[0]: row for row in result["rows"]}
        self.assertEqual(people["Mario Salazar"][1], "1")
        self.assertEqual(people["Rosa Antonio"][1], "1")
