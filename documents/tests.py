"""
Tests for the Document Management module.

The module makes four promises that a shared folder cannot, and each of them
is only worth as much as the test that holds it:

  * a file is never replaced, only superseded;
  * nothing is deleted by an ordinary user;
  * every consequential act reaches the document's own trail;
  * an archived document is not readable by everyone who could read it before.

The public document library is tested here too, because it reads from the same
table and a change to the lifecycle must not quietly empty the public page.
"""

import shutil
import tempfile

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User

from . import workflow
from .models import (
    DisposalAuthority,
    Document,
    DocumentEvent,
    DocumentStatus,
    DocumentType,
    EventType,
    RetentionAction,
    RetentionDisposition,
)

# Uploads go to a temporary directory: a test run must not leave PDFs behind
# in the Division's real media folder.
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="lgmed-imms-test-media-")


def pdf(name="document.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


class DocumentTestCase(TestCase):
    """Shared cast: the Chief, an approver, an encoder and an outsider."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.chief = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN, first_name="Divina"
        )
        cls.approver = User.objects.create_user(
            username="approver", password="pw", role=Role.LGMED_STAFF,
            first_name="Alonzo",
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", role=Role.ENCODER, first_name="Elmer"
        )
        cls.other = User.objects.create_user(
            username="other", password="pw", role=Role.ENCODER, first_name="Otto"
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER
        )
        cls.memo = DocumentType.objects.create(
            name="Memorandum", code="MEMO", retention_years=5
        )
        cls.permanent_type = DocumentType.objects.create(
            name="Minutes of Meeting",
            retention_years=10,
            retention_action=RetentionAction.PERMANENT,
        )

    def make(self, **overrides):
        fields = {
            "title": "Memorandum on compliance",
            "document_type": self.memo,
            "year": 2026,
            "owner": self.encoder,
            "created_by": self.encoder,
            "status": DocumentStatus.DRAFT,
        }
        fields.update(overrides)
        return Document.objects.create(**fields)

    def carry_to_completion(self, document):
        """Walk a document the whole way, through the real workflow."""
        workflow.register(document, self.encoder)
        workflow.submit_for_review(document, self.encoder)
        workflow.review(document, self.chief, notes="Noted.")
        workflow.assign(document, self.chief, assignee=self.encoder)
        workflow.start_processing(document, self.encoder)
        workflow.submit_for_approval(document, self.encoder)
        workflow.complete(document, self.approver)
        document.refresh_from_db()
        return document


# ---------------------------------------------------------------------------
# Control numbers and registration
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ControlNumberTests(DocumentTestCase):
    def test_a_control_number_is_issued_when_none_is_given(self):
        document = self.make()
        self.assertEqual(document.reference_number, "LGMED-2026-0001")

    def test_control_numbers_run_in_sequence_within_a_year(self):
        self.make()
        self.assertEqual(self.make().reference_number, "LGMED-2026-0002")

    def test_a_number_is_never_reissued_after_a_record_is_removed(self):
        """Gaps in a register are tolerable; a duplicate control number is not."""
        first = self.make()
        second = self.make()
        self.assertEqual(second.reference_number, "LGMED-2026-0002")
        second.delete()
        self.assertEqual(self.make().reference_number, "LGMED-2026-0003")
        self.assertEqual(first.reference_number, "LGMED-2026-0001")

    def test_a_number_supplied_by_the_office_is_kept(self):
        document = self.make(reference_number="RO13-2026-0999")
        self.assertEqual(document.reference_number, "RO13-2026-0999")

    def test_the_year_is_taken_from_the_document_dates_when_absent(self):
        document = Document(
            title="Undated",
            document_type=self.memo,
            owner=self.encoder,
            date_received=timezone.datetime(2024, 3, 9).date(),
        )
        document.save()
        self.assertEqual(document.year, 2024)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class VersionTests(DocumentTestCase):
    def test_uploading_a_revision_keeps_the_file_it_replaced(self):
        document = self.make(file=pdf("original.pdf"))
        workflow.register(document, self.encoder)
        self.assertEqual(document.version_count, 1)

        workflow.upload_version(
            document,
            self.encoder,
            uploaded_file=pdf("revised.pdf"),
            reason="Corrected the effectivity date.",
        )
        document.refresh_from_db()

        self.assertEqual(document.version_count, 2)
        first, second = (
            document.versions.order_by("version_number").first(),
            document.versions.order_by("version_number").last(),
        )
        self.assertIn("original", first.file.name)
        self.assertIn("revised", second.file.name)
        self.assertTrue(first.file.storage.exists(first.file.name))

    def test_the_current_file_points_at_the_newest_version(self):
        document = self.make(file=pdf("original.pdf"))
        workflow.register(document, self.encoder)
        version = workflow.upload_version(
            document, self.encoder, uploaded_file=pdf("revised.pdf"), reason="New."
        )
        document.refresh_from_db()
        self.assertEqual(document.file.name, version.file.name)

    def test_a_version_records_who_uploaded_it_and_why(self):
        document = self.make(file=pdf())
        workflow.register(document, self.encoder)
        version = workflow.upload_version(
            document,
            self.encoder,
            uploaded_file=pdf("v2.pdf"),
            reason="Annex B was missing.",
        )
        self.assertEqual(version.uploaded_by, self.encoder)
        self.assertEqual(version.reason, "Annex B was missing.")
        self.assertEqual(version.version_number, 2)

    def test_someone_with_no_stake_in_the_document_cannot_upload_a_version(self):
        document = self.make(file=pdf())
        workflow.register(document, self.encoder)
        with self.assertRaises(PermissionDenied):
            workflow.upload_version(
                document, self.other, uploaded_file=pdf("v2.pdf"), reason="Mine now."
            )


# ---------------------------------------------------------------------------
# The lifecycle
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class LifecycleTests(DocumentTestCase):
    def test_a_document_walks_the_whole_lifecycle(self):
        document = self.carry_to_completion(self.make())
        self.assertEqual(document.status, DocumentStatus.COMPLETED)
        self.assertEqual(document.approved_by, self.approver)
        self.assertIsNotNone(document.completed_at)

    def test_only_the_chief_may_name_the_focal_person(self):
        document = self.make(status=DocumentStatus.FOR_ASSIGNMENT)
        with self.assertRaises(PermissionDenied):
            workflow.assign(document, self.encoder, assignee=self.other)

        workflow.assign(document, self.chief, assignee=self.other)
        document.refresh_from_db()
        self.assertEqual(document.assigned_to, self.other)
        self.assertEqual(document.status, DocumentStatus.ASSIGNED)

    def test_assigning_implies_the_document_was_read(self):
        """A Chief who assigns has, by definition, reviewed it."""
        document = self.make(status=DocumentStatus.FOR_REVIEW)
        workflow.assign(document, self.chief, assignee=self.encoder)
        document.refresh_from_db()
        self.assertEqual(document.reviewed_by, self.chief)
        self.assertIsNotNone(document.reviewed_at)

    def test_reassignment_is_recorded_as_reassignment(self):
        document = self.make(status=DocumentStatus.FOR_ASSIGNMENT)
        workflow.assign(document, self.chief, assignee=self.encoder)
        workflow.assign(document, self.chief, assignee=self.other)
        self.assertTrue(
            document.events.filter(event_type=EventType.REASSIGNED).exists()
        )

    def test_an_encoder_cannot_approve_a_document(self):
        document = self.make(status=DocumentStatus.FOR_APPROVAL)
        with self.assertRaises(PermissionDenied):
            workflow.complete(document, self.encoder)


# ---------------------------------------------------------------------------
# Retention, archiving and disposal
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class RetentionTests(DocumentTestCase):
    def test_completion_starts_the_retention_clock_from_the_document_type(self):
        document = self.carry_to_completion(self.make())
        self.assertIsNotNone(document.retention_until)
        self.assertEqual(
            document.retention_until.year, timezone.localdate().year + 5
        )

    def test_a_type_marked_permanent_settles_the_document_on_completion(self):
        document = self.carry_to_completion(self.make(document_type=self.permanent_type))
        self.assertEqual(
            document.retention_disposition, RetentionDisposition.PERMANENT
        )

    def test_a_type_with_no_period_leaves_a_visible_gap(self):
        """Silence must not be read as 'dispose of it today'."""
        no_policy = DocumentType.objects.create(name="Uncategorised")
        document = self.carry_to_completion(self.make(document_type=no_policy))
        self.assertIsNone(document.retention_until)
        self.assertEqual(document.retention_summary, "No retention period set")

    def test_archiving_keeps_everything_and_only_restricts_access(self):
        document = self.carry_to_completion(self.make(file=pdf()))
        workflow.archive(document, self.approver, reason="Filed for the year.")
        document.refresh_from_db()

        self.assertEqual(document.status, DocumentStatus.ARCHIVED)
        self.assertTrue(document.file)
        self.assertEqual(document.version_count, 1)
        self.assertTrue(document.events.exists())
        self.assertEqual(document.owner, self.encoder)

    def test_archiving_takes_a_document_off_the_public_website(self):
        document = self.carry_to_completion(self.make())
        document.is_public = True
        document.save(update_fields=["is_public"])

        workflow.archive(document, self.approver)
        document.refresh_from_db()
        self.assertFalse(document.is_public)
        self.assertFalse(document.is_available_publicly)

    def test_an_unfinished_document_cannot_be_archived(self):
        document = self.make(status=DocumentStatus.IN_PROGRESS)
        with self.assertRaises(PermissionDenied):
            workflow.archive(document, self.approver)

    def test_an_encoder_cannot_archive(self):
        document = self.carry_to_completion(self.make())
        with self.assertRaises(PermissionDenied):
            workflow.archive(document, self.encoder)

    def test_an_archived_document_can_be_restored(self):
        document = self.carry_to_completion(self.make())
        workflow.archive(document, self.approver)
        workflow.restore(document, self.approver, reason="Needed for an audit.")
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.COMPLETED)
        self.assertIsNone(document.archived_at)

    def test_disposal_requires_an_archived_document_marked_for_disposal(self):
        authority = DisposalAuthority.objects.create(
            reference="NAP-RDS-2026-014",
            title="Regional records disposal schedule",
            approved_on=timezone.localdate(),
            approved_by="Regional Director",
        )
        document = self.carry_to_completion(self.make(file=pdf()))

        # Completed but not archived.
        with self.assertRaises(PermissionDenied):
            workflow.dispose(document, self.chief, authority=authority)

        workflow.archive(document, self.approver)
        # Archived, but no decision has been taken to dispose of it.
        with self.assertRaises(PermissionDenied):
            workflow.dispose(document, self.chief, authority=authority)

        workflow.set_retention(
            document,
            self.approver,
            retention_until=timezone.localdate(),
            disposition=RetentionDisposition.FOR_DISPOSAL,
        )
        # Marked for disposal, but the approver may not authorise disposal.
        with self.assertRaises(PermissionDenied):
            workflow.dispose(document, self.approver, authority=authority)

        workflow.dispose(document, self.chief, authority=authority, notes="Time up.")
        document.refresh_from_db()

        self.assertTrue(document.is_disposed)
        self.assertEqual(document.disposal_authority, authority)
        self.assertFalse(document.file)

    def test_disposal_keeps_the_record_and_the_whole_trail(self):
        authority = DisposalAuthority.objects.create(
            reference="RES-2026-01",
            title="Board resolution",
            approved_on=timezone.localdate(),
            approved_by="The Board",
        )
        document = self.carry_to_completion(self.make(file=pdf()))
        workflow.archive(document, self.approver)
        workflow.set_retention(
            document, self.approver, retention_until=timezone.localdate(),
            disposition=RetentionDisposition.FOR_DISPOSAL,
        )
        trail_before = document.events.count()
        workflow.dispose(document, self.chief, authority=authority)
        document.refresh_from_db()

        self.assertTrue(Document.objects.filter(pk=document.pk).exists())
        self.assertEqual(document.owner, self.encoder)
        self.assertEqual(document.version_count, 1)
        self.assertGreater(document.events.count(), trail_before)
        self.assertTrue(
            document.events.filter(event_type=EventType.DISPOSED).exists()
        )

    def test_retention_due_finds_what_has_run_out_and_ignores_the_settled(self):
        due = self.carry_to_completion(self.make(title="Due"))
        due.retention_until = timezone.localdate() - timezone.timedelta(days=1)
        due.save(update_fields=["retention_until"])

        settled = self.carry_to_completion(self.make(title="Settled"))
        settled.retention_until = timezone.localdate() - timezone.timedelta(days=1)
        settled.retention_disposition = RetentionDisposition.PERMANENT
        settled.save(update_fields=["retention_until", "retention_disposition"])

        found = set(Document.objects.retention_due().values_list("pk", flat=True))
        self.assertEqual(found, {due.pk})


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class TrailTests(DocumentTestCase):
    def test_registration_opens_the_trail(self):
        document = self.make(file=pdf())
        workflow.register(document, self.encoder)
        self.assertTrue(
            document.events.filter(event_type=EventType.REGISTERED).exists()
        )
        self.assertTrue(
            document.events.filter(event_type=EventType.UPLOADED).exists()
        )

    def test_the_actors_name_survives_the_account_being_removed(self):
        document = self.make()
        workflow.register(document, self.other)
        self.other.delete()

        event = document.events.filter(event_type=EventType.REGISTERED).first()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, "Otto")

    def test_a_view_is_recorded_once_a_day_per_person(self):
        document = self.make()
        self.assertIsNotNone(workflow.record_view(document, self.encoder))
        self.assertIsNone(workflow.record_view(document, self.encoder))
        self.assertEqual(
            DocumentEvent.objects.filter(
                document=document, event_type=EventType.VIEWED
            ).count(),
            1,
        )

    def test_every_download_is_recorded(self):
        document = self.make(file=pdf())
        workflow.register(document, self.encoder)
        workflow.record_download(document, self.encoder)
        workflow.record_download(document, self.encoder)
        self.assertEqual(
            document.events.filter(event_type=EventType.DOWNLOADED).count(), 2
        )


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AccessTests(DocumentTestCase):
    def test_an_archived_document_is_hidden_from_an_unconnected_user(self):
        document = self.carry_to_completion(self.make())
        workflow.archive(document, self.approver)

        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(document.get_absolute_url()).status_code, 403
        )

    def test_the_people_answerable_for_an_archived_document_may_still_read_it(self):
        document = self.carry_to_completion(self.make())
        workflow.archive(document, self.approver)

        for account in (self.encoder, self.approver, self.chief):
            self.client.force_login(account)
            self.assertEqual(
                self.client.get(document.get_absolute_url()).status_code,
                200,
                f"{account.username} was refused",
            )

    def test_the_register_leaves_the_archive_out_unless_it_is_asked_for(self):
        live = self.make(title="Live document")
        archived = self.carry_to_completion(self.make(title="Archived document"))
        workflow.archive(archived, self.approver)

        self.client.force_login(self.approver)
        response = self.client.get(reverse("documents:list"))
        self.assertContains(response, live.title)
        self.assertNotContains(response, archived.title)

        response = self.client.get(reverse("documents:list"), {"view": "archived"})
        self.assertContains(response, archived.title)

    def test_a_download_goes_through_the_application_and_is_logged(self):
        document = self.make(file=pdf())
        workflow.register(document, self.encoder)

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("documents:download", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()

        self.assertTrue(
            document.events.filter(
                event_type=EventType.DOWNLOADED, actor=self.viewer
            ).exists()
        )

    def test_a_disposed_documents_file_cannot_be_fetched(self):
        authority = DisposalAuthority.objects.create(
            reference="RES-2026-02",
            title="Board resolution",
            approved_on=timezone.localdate(),
            approved_by="The Board",
        )
        document = self.carry_to_completion(self.make(file=pdf()))
        workflow.archive(document, self.approver)
        workflow.set_retention(
            document, self.approver, retention_until=timezone.localdate(),
            disposition=RetentionDisposition.FOR_DISPOSAL,
        )
        workflow.dispose(document, self.chief, authority=authority)

        self.client.force_login(self.chief)
        self.assertEqual(
            self.client.get(
                reverse("documents:download", args=[document.pk])
            ).status_code,
            404,
        )

    def test_a_viewer_may_not_register_a_document(self):
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.get(reverse("documents:create")).status_code, 403
        )

    def test_the_retention_register_is_for_records_officers_only(self):
        self.client.force_login(self.encoder)
        self.assertEqual(
            self.client.get(reverse("documents:retention")).status_code, 403
        )
        self.client.force_login(self.approver)
        self.assertEqual(
            self.client.get(reverse("documents:retention")).status_code, 200
        )


    def test_a_refused_request_leaves_no_trace_of_having_viewed(self):
        """
        Access is checked before the view is recorded.

        A trail that says someone opened a document they were in fact refused
        is worse than no entry at all: it puts a person's name against an act
        they did not commit.
        """
        document = self.carry_to_completion(self.make())
        workflow.archive(document, self.approver)

        self.client.force_login(self.other)
        response = self.client.get(document.get_absolute_url())

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            document.events.filter(
                event_type=EventType.VIEWED, actor=self.other
            ).exists()
        )

    def test_opening_a_document_reaches_its_trail(self):
        document = self.make()
        self.client.force_login(self.viewer)
        self.client.get(document.get_absolute_url())

        self.assertTrue(
            document.events.filter(
                event_type=EventType.VIEWED, actor=self.viewer
            ).exists()
        )

# ---------------------------------------------------------------------------
# The public library
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PublicDocumentLibraryTests(TestCase):
    """
    The library is the page a visitor uses to find one issuance among many, so
    the filters carry the page: each must narrow the list without losing the
    others.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="owner", password="pw", role=Role.LGMED_STAFF
        )
        cls.memorandum = DocumentType.objects.create(name="Memorandum Circular")
        cls.advisory = DocumentType.objects.create(name="Advisory")
        cls.mc = cls.publish("MC on barangay assembly day", cls.memorandum, 2026)
        cls.old_mc = cls.publish("MC on the seal of good governance", cls.memorandum, 2025)
        cls.note = cls.publish("Advisory on report deadlines", cls.advisory, 2026)
        cls.publish(
            "Internal draft not for release",
            cls.advisory,
            2026,
            is_public=False,
            status=DocumentStatus.DRAFT,
        )

    @classmethod
    def publish(cls, title, document_type, year=2026, **overrides):
        fields = {
            "title": title,
            "document_type": document_type,
            "year": year,
            "owner": cls.owner,
            "status": DocumentStatus.COMPLETED,
            "is_public": True,
            "file": SimpleUploadedFile(f"{title}.pdf", b"%PDF-1.4 test"),
        }
        fields.update(overrides)
        return Document.objects.create(**fields)

    def test_library_lists_public_completed_documents_only(self):
        response = self.client.get(reverse("core:public_documents"))
        self.assertContains(response, self.mc.title)
        self.assertNotContains(response, "Internal draft not for release")

    def test_an_archived_document_leaves_the_public_library(self):
        workflow.archive(self.mc, self.owner)
        response = self.client.get(reverse("core:public_documents"))
        self.assertNotContains(response, self.mc.title)

    def test_type_counts_are_offered_beside_each_filter(self):
        response = self.client.get(reverse("core:public_documents"))
        counts = {row["name"]: row["total"] for row in response.context["document_types"]}
        self.assertEqual(counts, {"Memorandum Circular": 2, "Advisory": 1})

    def test_filtering_by_type_narrows_the_list(self):
        response = self.client.get(
            reverse("core:public_documents"), {"type": self.advisory.pk}
        )
        self.assertContains(response, self.note.title)
        self.assertNotContains(response, self.mc.title)

    def test_filtering_by_year_narrows_the_list(self):
        response = self.client.get(reverse("core:public_documents"), {"year": 2025})
        self.assertContains(response, self.old_mc.title)
        self.assertNotContains(response, self.note.title)

    def test_search_matches_the_title(self):
        response = self.client.get(
            reverse("core:public_documents"), {"q": "barangay assembly"}
        )
        self.assertContains(response, self.mc.title)
        self.assertNotContains(response, self.note.title)


# ---------------------------------------------------------------------------
# End to end, through the interface
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class EndToEndTests(DocumentTestCase):
    """
    The same journey as `LifecycleTests`, but driven through the URLs the
    office actually uses.

    Worth doing separately because the workflow functions can be perfectly
    correct while the form that feeds them refuses a valid submission, or the
    template that offers the button never renders it.
    """

    def register_through_the_form(self, **overrides):
        self.client.force_login(self.encoder)
        data = {
            "title": "Memorandum on compliance",
            "document_type": self.memo.pk,
            "reference_number": "",
            "subject": "Compliance with the full disclosure policy",
            "sender": "DILG Central Office",
            "date_received": timezone.localdate().isoformat(),
            "date_created": timezone.localdate().isoformat(),
            "due_date": "",
            "year": "",
            "owner": self.encoder.pk,
            "unit": "",
            "office": "LGMED",
            "description": "",
            "remarks": "Received at the counter.",
            "file": pdf("memo.pdf"),
        }
        data.update(overrides)
        return self.client.post(reverse("documents:create"), data)

    def test_a_document_can_be_registered_through_the_form(self):
        response = self.register_through_the_form()
        self.assertEqual(response.status_code, 302)

        document = Document.objects.get(title="Memorandum on compliance")
        self.assertEqual(document.owner, self.encoder)
        self.assertEqual(document.status, DocumentStatus.RECEIVED)
        self.assertEqual(document.year, timezone.localdate().year)
        self.assertTrue(document.reference_number.startswith("LGMED-"))
        self.assertEqual(document.version_count, 1)
        self.assertTrue(
            document.events.filter(event_type=EventType.REGISTERED).exists()
        )

    def test_a_document_with_no_date_received_is_a_draft(self):
        self.register_through_the_form(date_received="")
        document = Document.objects.get(title="Memorandum on compliance")
        self.assertEqual(document.status, DocumentStatus.DRAFT)

    def test_an_unacceptable_file_format_is_refused(self):
        response = self.register_through_the_form(
            file=SimpleUploadedFile(
                "payload.exe", b"MZ", content_type="application/x-msdownload"
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("file", response.context["form"].errors)
        self.assertFalse(
            Document.objects.filter(title="Memorandum on compliance").exists()
        )

    def test_the_whole_journey_through_the_endpoints(self):
        self.register_through_the_form()
        document = Document.objects.get(title="Memorandum on compliance")

        self.client.force_login(self.encoder)
        self.client.post(
            reverse("documents:submit_for_review", args=[document.pk]), {"notes": ""}
        )

        self.client.force_login(self.chief)
        self.client.post(
            reverse("documents:review", args=[document.pk]),
            {"notes": "For action within the week."},
        )
        self.client.post(
            reverse("documents:assign", args=[document.pk]),
            {
                "assigned_to": self.encoder.pk,
                "assignment_remarks": "Please draft the reply.",
                "due_date": "",
            },
        )

        self.client.force_login(self.encoder)
        self.client.post(reverse("documents:start", args=[document.pk]), {"notes": ""})
        self.client.post(
            reverse("documents:upload_version", args=[document.pk]),
            {"file": pdf("memo-v2.pdf"), "reason": "Annex B was missing."},
        )
        self.client.post(
            reverse("documents:submit_for_approval", args=[document.pk]), {"notes": ""}
        )

        self.client.force_login(self.approver)
        self.client.post(
            reverse("documents:complete", args=[document.pk]), {"notes": ""}
        )
        self.client.post(
            reverse("documents:archive", args=[document.pk]),
            {"reason": "Filed for the year."},
        )

        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.ARCHIVED)
        self.assertEqual(document.assigned_to, self.encoder)
        self.assertEqual(document.approved_by, self.approver)
        self.assertEqual(document.version_count, 2)
        self.assertIsNotNone(document.retention_until)

        recorded = set(document.events.values_list("event_type", flat=True))
        for expected in (
            EventType.REGISTERED,
            EventType.UPLOADED,
            EventType.STATUS_CHANGED,
            EventType.ASSIGNED,
            EventType.VERSION_UPLOADED,
            EventType.APPROVED,
            EventType.ARCHIVED,
        ):
            self.assertIn(expected, recorded, f"{expected} never reached the trail")

    def test_an_encoder_cannot_assign_through_the_endpoint(self):
        """The button is hidden, but hiding it is not the control."""
        document = self.make(status=DocumentStatus.FOR_ASSIGNMENT)
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("documents:assign", args=[document.pk]),
            {"assigned_to": self.other.pk, "assignment_remarks": "", "due_date": ""},
        )
        self.assertEqual(response.status_code, 403)
        document.refresh_from_db()
        self.assertIsNone(document.assigned_to)

    def test_a_version_upload_without_a_reason_is_refused(self):
        document = self.make(file=pdf())
        workflow.register(document, self.encoder)

        self.client.force_login(self.encoder)
        self.client.post(
            reverse("documents:upload_version", args=[document.pk]),
            {"file": pdf("v2.pdf"), "reason": ""},
        )
        document.refresh_from_db()
        self.assertEqual(document.version_count, 1)

    def test_a_missing_file_reads_as_not_found_rather_than_a_server_fault(self):
        document = self.make(file="documents/2026/never-written.pdf")
        self.client.force_login(self.encoder)
        response = self.client.get(reverse("documents:download", args=[document.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            document.events.filter(event_type=EventType.DOWNLOADED).exists(),
            "a download that never happened must not be recorded",
        )

    def test_the_monitoring_dashboard_counts_what_the_register_holds(self):
        self.make(status=DocumentStatus.FOR_REVIEW)
        self.carry_to_completion(self.make(title="Finished"))

        self.client.force_login(self.chief)
        response = self.client.get(reverse("documents:dashboard"))
        self.assertEqual(response.status_code, 200)
        summary = response.context["summary"]
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["for_review"], 1)
        self.assertEqual(summary["completed"], 1)
