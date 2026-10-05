"""
Tests for Incoming Monitoring.

The workflow rule is what these mostly assert: an encoder records a document
but cannot assign it, and the ways round that - posting to the assign URL
directly, editing a record after the Chief has acted on it - are refused by the
server rather than merely hidden from the page.
"""

import datetime
import os

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
        workflow.acknowledge(document, self.focal)
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
        workflow.acknowledge(document, self.focal)
        self.client.force_login(self.other_focal)
        response = self.client.post(
            reverse("outgoing:add_update", args=[document.outgoing_document.pk]),
            {"action_taken": "Meddling.", "status": IncomingStatus.IN_PROGRESS},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(document.updates.count(), 0)

    def test_returning_sends_the_document_back_to_the_focal_person(self):
        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
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
        workflow.acknowledge(document, self.focal)
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
        workflow.acknowledge(document, self.focal)
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


class LgmedCodeTests(IncomingTestCase):
    """
    Incoming first, assignment second, LGMED code third - and only once.
    """

    def expected_code(self, initials, number, on=None):
        on = on or timezone.localdate()
        return f"LGMED-13 - {initials} - {on:%Y-%m-%d}-{number:04d}"

    def test_a_recorded_document_has_no_lgmed_code(self):
        document = self.make_document()
        self.assertIsNone(document.lgmed_code)
        self.assertEqual(document.tracking_number, "2026-0001")

    def test_reviewing_does_not_issue_a_code(self):
        document = self.make_document()
        workflow.review(document, self.chief, "Prepare a reply.")
        document.refresh_from_db()
        self.assertIsNone(document.lgmed_code)

    def test_assigning_issues_the_code_from_the_focal_persons_initials(self):
        document = self.assign_to_focal(self.make_document())
        document.refresh_from_db()
        self.assertEqual(document.lgmed_code, self.expected_code("MS", 1))
        self.assertEqual(document.tracking_number, document.lgmed_code)
        self.assertIn(
            document.lgmed_code, document.events.get(event_type=EventType.ASSIGNED).detail
        )

    def test_configured_initials_carry_the_middle_initial(self):
        self.focal.code_initials = "rgfj"
        self.focal.save()
        document = self.assign_to_focal(self.make_document())
        self.assertEqual(document.lgmed_code, self.expected_code("RGFJ", 1))

    def test_reassigning_and_acting_never_issue_another_code(self):
        document = self.assign_to_focal(self.make_document())
        issued = document.lgmed_code

        self.assign_to_focal(document, assignee=self.other_focal)
        workflow.acknowledge(document, self.other_focal)
        workflow.add_update(
            document, self.other_focal,
            IncomingUpdate(action_taken="Drafted the reply",
                           status=IncomingStatus.COMPLETED),
        )
        document.refresh_from_db()
        self.assertEqual(document.lgmed_code, issued)

    def test_numbers_run_on_across_documents(self):
        first = self.assign_to_focal(self.make_document())
        second = self.assign_to_focal(
            self.make_document(docket_number="2026-0002"), assignee=self.other_focal
        )
        self.assertEqual(first.lgmed_code, self.expected_code("MS", 1))
        self.assertEqual(second.lgmed_code, self.expected_code("RA", 2))

    def test_numbers_continue_after_the_outgoing_register(self):
        """A code issued here never repeats one written in the spreadsheet."""
        from outgoing.models import OutgoingDocument

        today = timezone.localdate()
        OutgoingDocument.objects.create(
            control_code=f"LGMED-13 - (DBA) - {today:%Y}-01-05-0041"
        )
        document = self.assign_to_focal(self.make_document())
        self.assertEqual(document.lgmed_code, self.expected_code("MS", 42))

    def test_a_deleted_documents_number_is_not_issued_again(self):
        self.assign_to_focal(self.make_document()).delete()
        document = self.assign_to_focal(
            self.make_document(docket_number="2026-0002")
        )
        self.assertEqual(document.lgmed_code, self.expected_code("MS", 2))

    def test_numbering_restarts_each_year(self):
        from outgoing.codes import issue_code

        self.assertTrue(issue_code(self.focal, datetime.date(2025, 12, 31)).endswith(
            "2025-12-31-0001"
        ))
        self.assertTrue(issue_code(self.focal, datetime.date(2025, 12, 31)).endswith(
            "2025-12-31-0002"
        ))
        self.assertTrue(issue_code(self.focal, datetime.date(2026, 1, 2)).endswith(
            "2026-01-02-0001"
        ))

    def test_the_encoders_form_cannot_carry_a_code(self):
        from .forms import IncomingDocumentForm

        self.assertNotIn("lgmed_code", IncomingDocumentForm().fields)


class OutgoingHandoverTests(IncomingTestCase):
    """Acknowledged, the document moves to Outgoing Monitoring; action is taken there."""

    def acknowledged(self):
        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
        return document

    def test_the_code_has_no_parentheses(self):
        document = self.assign_to_focal(self.make_document())
        self.assertNotIn("(", document.lgmed_code)
        self.assertTrue(document.lgmed_code.startswith("LGMED-13 - MS - "))

    def test_nothing_moves_before_acknowledgement(self):
        from outgoing.models import OutgoingDocument

        document = self.assign_to_focal(self.make_document())
        self.assertFalse(OutgoingDocument.objects.exists())
        self.assertIsNone(document.outgoing_document)
        self.assertFalse(document.may_be_updated_by(self.focal))

    def test_acknowledging_opens_the_outgoing_record_under_the_same_code(self):
        from outgoing.models import OutgoingDocument

        document = self.acknowledged()
        outgoing = OutgoingDocument.objects.get()
        self.assertEqual(outgoing.control_code, document.lgmed_code)
        self.assertEqual(outgoing.incoming, document)
        self.assertEqual(outgoing.incoming_reference, document.docket_number)
        self.assertIsNone(outgoing.date_sent)
        self.assertEqual(document.action_url, outgoing.get_absolute_url())

    def test_acknowledging_through_the_page_lands_in_outgoing(self):
        document = self.assign_to_focal(self.make_document())
        self.client.force_login(self.focal)
        response = self.client.post(reverse("incoming:acknowledge", args=[document.pk]))
        document.refresh_from_db()
        self.assertRedirects(response, document.outgoing_document.get_absolute_url())

    def test_a_reassigned_document_keeps_its_one_outgoing_record(self):
        from outgoing.models import OutgoingDocument

        document = self.acknowledged()
        self.assign_to_focal(document, assignee=self.other_focal)
        workflow.acknowledge(document, self.other_focal)
        self.assertEqual(OutgoingDocument.objects.count(), 1)

    def test_the_focal_person_updates_and_completes_in_outgoing(self):
        document = self.acknowledged()
        record = document.outgoing_document
        self.client.force_login(self.focal)
        response = self.client.post(
            reverse("outgoing:add_update", args=[record.pk]),
            {"action_taken": "Reply sent.", "status": IncomingStatus.COMPLETED},
        )
        self.assertRedirects(response, record.get_absolute_url())
        document.refresh_from_db()
        self.assertTrue(document.is_completed)

    def test_the_chief_returns_for_revision_in_outgoing(self):
        document = self.acknowledged()
        self.client.force_login(self.chief)
        self.client.post(
            reverse("outgoing:return", args=[document.outgoing_document.pk]),
            {"remarks": "Check the figures."},
        )
        document.refresh_from_db()
        self.assertEqual(document.status, IncomingStatus.RETURNED)

    def test_the_incoming_urls_for_action_are_gone(self):
        from django.urls import NoReverseMatch

        with self.assertRaises(NoReverseMatch):
            reverse("incoming:add_update", args=[1])

    def test_recording_the_communication_sent(self):
        document = self.acknowledged()
        record = document.outgoing_document
        self.client.force_login(self.focal)
        response = self.client.post(
            reverse("outgoing:transmittal", args=[record.pk]),
            {
                "date_sent": timezone.localdate().isoformat(),
                "communication_type": "Letter",
                "subject": "Reply on the SGLG validation",
                "sent_to": "Office of the Regional Director",
                "sent_via": "Email",
            },
        )
        self.assertRedirects(response, record.get_absolute_url())
        record.refresh_from_db()
        self.assertEqual(record.control_code, document.lgmed_code)
        self.assertEqual(record.date_sent, timezone.localdate())
        self.assertTrue(document.events.filter(event_type=EventType.OUTGOING).exists())
        document.refresh_from_db()
        self.assertEqual(document.status, IncomingStatus.ACKNOWLEDGED)

    def test_only_the_focal_person_or_the_chief_may_act(self):
        document = self.acknowledged()
        record = document.outgoing_document
        self.client.force_login(self.other_focal)
        self.assertEqual(
            self.client.get(reverse("outgoing:transmittal", args=[record.pk])).status_code,
            403,
        )

    def test_the_pages_render(self):
        document = self.acknowledged()
        record = document.outgoing_document
        self.client.force_login(self.focal)
        page = self.client.get(record.get_absolute_url())
        self.assertContains(page, document.lgmed_code)
        self.assertContains(page, reverse("outgoing:add_update", args=[record.pk]))
        self.assertContains(
            self.client.get(document.get_absolute_url()), record.get_absolute_url()
        )
        self.assertContains(self.client.get(reverse("outgoing:list")), document.lgmed_code)
        self.assertEqual(
            self.client.get(reverse("outgoing:transmittal", args=[record.pk])).status_code,
            200,
        )


class DocumentRegisterSyncTests(IncomingTestCase):
    """Every incoming document is in the Documents register, and moves with it."""

    def entry(self, document):
        from documents.models import Document

        return Document.objects.get(incoming=document)

    def test_recording_registers_the_document(self):
        document = self.make_document()
        entry = self.entry(document)
        self.assertEqual(entry.reference_number, "2026-0001")
        self.assertEqual(entry.title, document.subject)
        self.assertEqual(entry.sender, document.source_office)
        self.assertEqual(entry.owner, self.encoder)
        self.assertEqual(entry.status, "FOR_REVIEW")
        self.assertTrue(entry.events.filter(event_type="REGISTERED").exists())

    def test_the_chiefs_review_moves_it_to_for_assignment(self):
        document = self.make_document()
        workflow.review(document, self.chief, "Prepare a reply.")
        entry = self.entry(document)
        self.assertEqual(entry.status, "FOR_ASSIGNMENT")
        self.assertEqual(entry.review_notes, "Prepare a reply.")

    def test_assignment_carries_the_focal_person_and_the_lgmed_code(self):
        document = self.assign_to_focal(self.make_document())
        entry = self.entry(document)
        self.assertEqual(entry.status, "ASSIGNED")
        self.assertEqual(entry.assigned_to, self.focal)
        self.assertEqual(entry.reference_number, document.lgmed_code)
        self.assertIn("2026-0001", entry.description)

    def test_acknowledging_and_completing_follow_through(self):
        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
        self.assertEqual(self.entry(document).status, "IN_PROGRESS")

        workflow.add_update(
            document, self.focal,
            IncomingUpdate(action_taken="Reply sent.", status=IncomingStatus.COMPLETED),
        )
        entry = self.entry(document)
        self.assertEqual(entry.status, "COMPLETED")
        self.assertIsNotNone(entry.completed_at)

        workflow.return_for_revision(document, self.chief, "Check the figures.")
        entry = self.entry(document)
        self.assertEqual(entry.status, "IN_PROGRESS")
        self.assertIsNone(entry.completed_at)

    def test_one_entry_per_document(self):
        from documents.models import Document

        document = self.assign_to_focal(self.make_document())
        workflow.acknowledge(document, self.focal)
        self.assertEqual(Document.objects.filter(incoming=document).count(), 1)

    def test_the_entry_cannot_be_moved_from_the_register(self):
        from documents import workflow as register_workflow

        document = self.assign_to_focal(self.make_document())
        entry = self.entry(document)
        self.assertFalse(entry.may_be_edited_by(self.chief))
        self.assertFalse(entry.may_be_assigned_by(self.chief))
        with self.assertRaises(PermissionDenied):
            register_workflow.start_processing(entry, self.focal)
        with self.assertRaises(PermissionDenied):
            register_workflow.cancel(entry, self.chief, reason="No.")

    def test_the_register_page_points_back_to_incoming(self):
        document = self.make_document()
        self.client.force_login(self.chief)
        response = self.client.get(self.entry(document).get_absolute_url())
        self.assertContains(response, document.get_absolute_url())
        self.assertNotContains(response, "Mark reviewed")

    def test_the_backfill_registers_what_came_before(self):
        from django.core.management import call_command

        from documents.models import Document

        document = IncomingDocument.objects.create(
            docket_number="2025-0900",
            subject="An old document",
            document_type=self.document_type,
            date_received=datetime.date(2025, 3, 1),
            source_office="Province of Agusan del Norte",
            created_by=self.encoder,
            status=IncomingStatus.IMPORTED,
        )
        call_command("sync_document_register", stdout=open(os.devnull, "w"))
        call_command("sync_document_register", stdout=open(os.devnull, "w"))
        entry = Document.objects.get(incoming=document)
        self.assertEqual(entry.status, "RECEIVED")
        self.assertEqual(entry.year, 2025)
        self.assertEqual(Document.objects.filter(incoming=document).count(), 1)
