"""
Tests for the PPA module.

The module's premise is that nothing becomes public by accident, so most of
what is asserted here is a refusal: that an uploaded file is not reachable, that
a clean screening is not an approval, that an approval is not a publication,
that a child of an unpublished record is not visible however it is addressed,
and that the roles which may encode, review and publish are three different
sets of people.

The tests that check the screening engine are written against the *decision*
it produces rather than against its regular expressions. A rule that stops
matching a phone number should fail a test about phone numbers, not a test
about the shape of a finding dictionary.
"""

import datetime
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.testing import close_response
from django.urls import reverse

from accounts.models import Role, Section, User
from audit.models import Action, AuditEvent

from . import screening
from .forms import DocumentAuthorityForm
from .models import (
    Activity,
    DocumentKind,
    DocumentStatus,
    OrganizationalOutcome,
    Program,
    ProgramStatus,
    Project,
    PublicationAuthority,
    PublicationStatus,
    RiskLevel,
    SubProject,
    SupportingDocument,
)
from .public import public_statistics, visible

TODAY = datetime.date(2026, 9, 14)


def temp_media():
    """
    Both roots redirected into one throwaway directory, kept apart inside it.

    Overriding the two settings is enough: the default storage resolves
    MEDIA_ROOT on use, and `ProtectedFileSystemStorage` does the same with
    PROTECTED_MEDIA_ROOT. If that ever stops being true, the first test below
    is the one that notices.
    """
    root = Path(tempfile.mkdtemp())
    return override_settings(
        MEDIA_ROOT=root / "media",
        PROTECTED_MEDIA_ROOT=root / "protected",
    ), root


class PPATestCase(TestCase):
    """Shared fixtures: the three roles, and a programme with a tree under it."""

    @classmethod
    def setUpTestData(cls):
        cls.section = Section.objects.create(name="Field Operations Section")

        cls.encoder = User.objects.create_user(
            "encoder", password="x", role=Role.ENCODER, first_name="Ellen",
            last_name="Encoder",
        )
        cls.reviewer = User.objects.create_user(
            "reviewer", password="x", role=Role.LGMED_STAFF, first_name="Rey",
            last_name="Reviewer",
        )
        cls.publisher = User.objects.create_user(
            "publisher", password="x", role=Role.ADMIN, first_name="Pam",
            last_name="Publisher",
        )
        cls.viewer = User.objects.create_user("viewer", password="x", role=Role.VIEWER)

        cls.program = Program.objects.create(
            title="Seal of Good Local Governance",
            outcome_code=OrganizationalOutcome.OO1,
            description="Assessment and conferment for local government units.",
            status=ProgramStatus.ACTIVE,
            responsible_office=cls.section,
            created_by=cls.encoder,
        )
        cls.project = Project.objects.create(
            title="SGLG Regional Assessment 2026",
            program=cls.program,
            created_by=cls.encoder,
        )
        cls.sub_project = SubProject.objects.create(
            title="Agusan del Norte Cluster",
            project=cls.project,
            created_by=cls.encoder,
        )
        cls.activity = Activity.objects.create(
            title="Orientation of Regional Assessors",
            sub_project=cls.sub_project,
            activity_date=TODAY,
            location="Butuan City",
            created_by=cls.encoder,
        )

        # The standing memorandum most tests release under. A file cannot be
        # published without one, so a test about publication that did not
        # record an authority would only ever be testing the refusal.
        cls.authority = PublicationAuthority.objects.create(
            reference="LGMED Memorandum No. 2026-001",
            title="Standing authority to publish programme information",
            approved_on=TODAY - datetime.timedelta(days=30),
            approved_by="Regional Director",
            created_by=cls.publisher,
        )

    def publish_chain(self, *records):
        """Take records all the way to published, in order."""
        for record in records:
            record.approve(self.reviewer)
            record.publish(self.publisher)
            record.refresh_from_db()

    def clear_for_release(self, *documents):
        """
        Approve a file and cite the standing memorandum against it - the two
        things publication actually requires.
        """
        for document in documents:
            document.authority = self.authority
            document.approve(self.reviewer)
        return documents[0] if len(documents) == 1 else documents


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


class StructureTests(PPATestCase):
    def test_every_level_resolves_its_outcome(self):
        """An activity four levels down still knows which Outcome it serves."""
        for record in (self.program, self.project, self.sub_project, self.activity):
            self.assertEqual(record.outcome, OrganizationalOutcome.OO1)

    def test_ancestors_are_root_first(self):
        self.assertEqual(
            [r.pk for r in self.activity.ancestors],
            [self.program.pk, self.project.pk, self.sub_project.pk],
        )

    def test_activity_needs_exactly_one_parent(self):
        orphan = Activity(title="Nowhere")
        with self.assertRaises(ValidationError):
            orphan.full_clean()

        both = Activity(title="Both", project=self.project,
                        sub_project=self.sub_project)
        with self.assertRaises(ValidationError):
            both.clean()

    def test_slug_is_unique_and_derived_from_the_title(self):
        twin = Program.objects.create(title="Seal of Good Local Governance")
        self.assertEqual(self.program.slug, "seal-of-good-local-governance")
        self.assertEqual(twin.slug, "seal-of-good-local-governance-2")

    def test_new_records_start_as_drafts(self):
        for record in (self.program, self.project, self.sub_project, self.activity):
            self.assertEqual(record.publication_status, PublicationStatus.DRAFT)
            self.assertFalse(record.is_published)


# ---------------------------------------------------------------------------
# The publication workflow
# ---------------------------------------------------------------------------


class WorkflowTests(PPATestCase):
    def test_only_approved_content_may_be_published(self):
        with self.assertRaises(ValidationError):
            self.program.publish(self.publisher)

        self.program.submit_for_review(self.encoder)
        with self.assertRaises(ValidationError):
            self.program.publish(self.publisher)

        self.program.approve(self.reviewer)
        self.program.publish(self.publisher)
        self.assertTrue(self.program.is_published)

    def test_a_child_cannot_be_published_before_its_parent(self):
        self.project.approve(self.reviewer)
        with self.assertRaises(ValidationError):
            self.project.publish(self.publisher)

        self.publish_chain(self.program)
        self.project.refresh_from_db()
        self.project.publish(self.publisher)
        self.assertTrue(self.project.is_published)

    def test_unpublishing_a_parent_takes_its_children_down(self):
        self.publish_chain(self.program, self.project, self.sub_project)

        self.program.unpublish(self.publisher)

        self.project.refresh_from_db()
        self.sub_project.refresh_from_db()
        self.assertEqual(self.project.publication_status, PublicationStatus.UNPUBLISHED)
        self.assertEqual(
            self.sub_project.publication_status, PublicationStatus.UNPUBLISHED
        )

    def test_editing_published_content_withdraws_it(self):
        self.publish_chain(self.program)
        self.program.description = "Something different."
        self.program.save()
        self.program.touch_content(self.encoder)
        self.assertEqual(
            self.program.publication_status, PublicationStatus.UNPUBLISHED
        )

    def test_editing_approved_content_withdraws_the_approval(self):
        self.program.approve(self.reviewer)
        self.program.touch_content(self.encoder)
        self.assertEqual(self.program.publication_status, PublicationStatus.DRAFT)
        self.assertIsNone(self.program.approved_at)

    def test_restoring_from_the_archive_returns_a_draft(self):
        self.publish_chain(self.program)
        self.program.archive(self.publisher)
        self.assertEqual(self.program.publication_status, PublicationStatus.ARCHIVED)

        self.program.restore(self.publisher)
        self.assertEqual(self.program.publication_status, PublicationStatus.DRAFT)
        self.assertIsNone(self.program.approved_at)

    def test_the_record_names_everyone_who_touched_it(self):
        self.program.submit_for_review(self.encoder)
        self.program.approve(self.reviewer)
        self.program.publish(self.publisher)

        self.assertEqual(self.program.submitted_by, self.encoder)
        self.assertEqual(self.program.reviewed_by, self.reviewer)
        self.assertEqual(self.program.approved_by, self.reviewer)
        self.assertEqual(self.program.published_by, self.publisher)
        self.assertIsNotNone(self.program.published_at)


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------


class ScreeningEngineTests(TestCase):
    """The detectors, tested through the decision they produce."""

    def screen(self, text, extension="txt"):
        extraction = screening.extract(text.encode("utf-8"), extension)
        findings = screening.detect(extraction)
        return findings, screening.classify(findings)

    def codes(self, findings):
        return {finding["code"] for finding in findings}

    def test_a_tin_is_high_risk(self):
        findings, risk = self.screen("Payee TIN: 123-456-789-000 for the claim.")
        self.assertIn("tin", self.codes(findings))
        self.assertEqual(risk, RiskLevel.HIGH)

    def test_confidentiality_markings_are_high_risk(self):
        for marking in (
            "STRICTLY CONFIDENTIAL",
            "FOR INTERNAL USE ONLY",
            "NOT FOR PUBLIC DISTRIBUTION",
            "RESTRICTED",
        ):
            with self.subTest(marking=marking):
                findings, risk = self.screen(f"{marking}\nRegional report for 2026.")
                self.assertEqual(risk, RiskLevel.HIGH, marking)

    def test_credentials_are_high_risk(self):
        findings, risk = self.screen("db password: Sup3rSecret!\nhost: reports")
        self.assertIn("password", self.codes(findings))
        self.assertEqual(risk, RiskLevel.HIGH)

    def test_an_attendance_sheet_is_high_risk(self):
        findings, risk = self.screen(
            "ATTENDANCE SHEET\nOrientation of Assessors\nName / Signature"
        )
        self.assertIn("attendance_sheet", self.codes(findings))
        self.assertEqual(risk, RiskLevel.HIGH)

    def test_a_mobile_number_needs_review(self):
        findings, risk = self.screen("Contact the focal person at 0917 555 1234.")
        self.assertIn("mobile", self.codes(findings))
        self.assertEqual(risk, RiskLevel.REVIEW_REQUIRED)

    def test_a_personal_email_needs_review(self):
        findings, risk = self.screen("Send it to juandelacruz@gmail.com please.")
        self.assertIn("personal_email", self.codes(findings))
        self.assertEqual(risk, RiskLevel.REVIEW_REQUIRED)

    def test_evidence_is_masked(self):
        """The review screen must never reprint the number it is warning about."""
        findings, _ = self.screen("TIN: 123-456-789-000")
        evidence = next(f for f in findings if f["code"] == "tin")["evidence"]
        self.assertTrue(evidence)
        for example in evidence:
            self.assertNotIn("123-456-789-000", example)
            self.assertIn("*", example)

    def test_clean_text_is_low_risk_and_still_not_an_approval(self):
        findings, risk = self.screen(
            "The Division conducted a regional orientation on the assessment "
            "criteria for local government units."
        )
        self.assertEqual(findings, [])
        self.assertEqual(risk, RiskLevel.LOW)

    def test_findings_are_ordered_most_serious_first(self):
        findings, _ = self.screen(
            "Contact 0917 555 1234. TIN 123-456-789-000. CONFIDENTIAL."
        )
        severities = [f["severity"] for f in findings]
        self.assertEqual(severities, sorted(severities, key=lambda s: {
            "HIGH": 0, "MEDIUM": 1, "LOW": 2}[s]))

    def test_an_unreadable_file_is_never_low_risk(self):
        """
        The point of the whole module: silence from the scanner is not safety.
        """
        extraction = screening.extract(b"\x00\x01\x02 binary rubbish", "jpg")
        findings = screening.detect(extraction) + screening.coverage_findings(
            extraction, "photo.jpg"
        )
        self.assertNotEqual(screening.classify(findings), RiskLevel.LOW)
        self.assertIn("unreadable", {f["code"] for f in findings})

    def test_a_legacy_office_file_is_never_reported_as_fully_read(self):
        extraction = screening.extract(b"junk" * 200, "doc")
        self.assertFalse(extraction.complete)

    def test_docx_text_and_properties_are_read(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "docProps/core.xml",
                '<?xml version="1.0"?><cp:coreProperties>'
                "<dc:creator>Juan Dela Cruz</dc:creator></cp:coreProperties>",
            )
            archive.writestr(
                "word/document.xml",
                "<w:document><w:body><w:p><w:r><w:t>"
                "This report is CONFIDENTIAL."
                "</w:t></w:r></w:p></w:body></w:document>",
            )
        extraction = screening.extract(buffer.getvalue(), "docx")
        self.assertIn("CONFIDENTIAL", extraction.text)
        self.assertIn("Juan Dela Cruz", extraction.text)

    def test_xlsx_reports_the_sheet_a_finding_came_from(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "xl/workbook.xml",
                '<workbook><sheets><sheet name="Participants" sheetId="1"/>'
                "</sheets></workbook>",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                "<worksheet><row><c><v>TIN 123-456-789-000</v></c></row></worksheet>",
            )
        extraction = screening.extract(buffer.getvalue(), "xlsx")
        findings = screening.detect(extraction)
        tin = next(f for f in findings if f["code"] == "tin")
        self.assertIn("sheet: Participants", tin["locations"])


# ---------------------------------------------------------------------------
# Documents: storage, screening, approval, publication
# ---------------------------------------------------------------------------


class DocumentTests(PPATestCase):
    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

    def attach(self, content=b"A clean regional report.", name="report.txt",
               owner=None, **kwargs):
        owner = owner or self.program
        document = SupportingDocument(
            title=kwargs.pop("title", "Regional report"),
            kind=DocumentKind.REPORT,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile(name, content),
            **kwargs,
        )
        setattr(document, {
            Program: "program", Project: "project",
            SubProject: "sub_project", Activity: "activity",
        }[type(owner)], owner)
        document.save()
        return document

    def test_the_uploaded_file_lands_outside_the_public_media_root(self):
        document = self.attach()
        stored = Path(document.file.path)
        self.assertTrue(stored.exists())
        self.assertTrue(str(stored).startswith(str(self.root / "protected")))
        self.assertFalse(str(stored).startswith(str(self.root / "media")))

    def test_an_unscreened_document_is_not_treated_as_safe(self):
        document = self.attach()
        self.assertEqual(document.risk_level, RiskLevel.REVIEW_REQUIRED)
        self.assertFalse(document.is_screened)

    def test_screening_records_its_result_on_the_document(self):
        document = self.attach(b"Payee TIN: 123-456-789-000")
        screening.screen_document(document)
        document.refresh_from_db()

        self.assertEqual(document.risk_level, RiskLevel.HIGH)
        self.assertEqual(document.status, DocumentStatus.SCREENED)
        self.assertIsNotNone(document.screened_at)
        self.assertTrue(document.screening_findings)
        self.assertIn("Read by", document.screening_notes)

    def test_a_high_risk_document_is_not_offered_one_click_approval(self):
        document = self.attach(b"STRICTLY CONFIDENTIAL")
        screening.screen_document(document)
        self.assertFalse(document.may_be_approved_directly)

    def test_an_approved_document_is_still_not_public(self):
        """Approval clears the content. It does not put anything anywhere."""
        document = self.attach()
        screening.screen_document(document)
        self.clear_for_release(document)

        self.assertFalse(document.public_file)
        self.assertIsNone(document.public_url)

    def test_publishing_creates_a_separate_public_copy(self):
        document = self.attach(b"The regional assessment summary.")
        screening.screen_document(document)
        self.clear_for_release(document)
        self.publish_chain(self.program)
        document.publish(self.publisher)

        self.assertTrue(document.public_file)
        public = Path(document.public_file.path)
        internal = Path(document.file.path)

        self.assertNotEqual(public, internal)
        self.assertTrue(str(public).startswith(str(self.root / "media")))
        self.assertTrue(public.exists())
        self.assertTrue(internal.exists())
        self.assertEqual(public.read_bytes(), internal.read_bytes())

    def test_the_public_copy_is_named_from_the_title_not_the_filename(self):
        document = self.attach(
            name="SGLG-2025-final-BUTUAN-revised-by-jdelacruz.txt",
            title="SGLG 2025 Regional Summary",
        )
        screening.screen_document(document)
        self.clear_for_release(document)
        self.publish_chain(self.program)
        document.refresh_from_db()

        public_name = Path(document.public_file.name).name
        self.assertEqual(public_name, "sglg-2025-regional-summary.txt")
        self.assertNotIn("jdelacruz", public_name)

    def test_withdrawing_deletes_the_public_copy_from_disk(self):
        document = self.attach()
        screening.screen_document(document)
        self.clear_for_release(document)
        self.publish_chain(self.program)
        document.publish(self.publisher)
        public = Path(document.public_file.path)

        document.withdraw(self.publisher)

        self.assertFalse(public.exists())
        self.assertFalse(document.public_file)
        self.assertIsNone(document.public_url)
        self.assertTrue(Path(document.file.path).exists())

    def test_an_unapproved_document_cannot_be_published(self):
        document = self.attach()
        with self.assertRaises(ValidationError):
            document.publish(self.publisher)

    def test_publishing_a_record_publishes_only_its_approved_files(self):
        approved = self.attach(title="Approved summary")
        pending = self.attach(title="Pending annex")
        screening.screen_document(approved)
        screening.screen_document(pending)
        self.clear_for_release(approved)

        self.program.approve(self.reviewer)
        self.program.publish(self.publisher)

        approved.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(approved.status, DocumentStatus.PUBLISHED)
        self.assertEqual(pending.status, DocumentStatus.SCREENED)
        self.assertFalse(pending.public_file)

    def test_unpublishing_a_record_withdraws_its_files(self):
        document = self.attach()
        screening.screen_document(document)
        self.clear_for_release(document)
        self.program.approve(self.reviewer)
        self.program.publish(self.publisher)
        document.refresh_from_db()
        public = Path(document.public_file.path)

        self.program.unpublish(self.publisher)

        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.WITHDRAWN)
        self.assertFalse(public.exists())

    def test_submitting_screens_the_attached_files(self):
        self.attach(b"Mobile 0917 555 1234")
        outcome = self.program.submit_for_review(self.encoder)
        self.assertEqual(outcome, PublicationStatus.REVIEW_REQUIRED)

    def test_submitting_with_clean_files_goes_straight_to_review(self):
        self.attach(b"A description of the regional orientation.")
        outcome = self.program.submit_for_review(self.encoder)
        self.assertEqual(outcome, PublicationStatus.FOR_REVIEW)

    def test_a_document_belongs_to_exactly_one_record(self):
        document = SupportingDocument(
            title="Stray", program=self.program, project=self.project,
            file=SimpleUploadedFile("x.txt", b"x"),
        )
        with self.assertRaises(ValidationError):
            document.clean()


# ---------------------------------------------------------------------------
# What the public may see
# ---------------------------------------------------------------------------


class PublicVisibilityTests(PPATestCase):
    def test_an_unpublished_record_is_not_visible(self):
        self.assertFalse(visible(self.program))

    def test_a_published_child_of_an_unpublished_parent_is_not_visible(self):
        """
        The one that matters. The project row says PUBLISHED, but the programme
        above it does not, so the public may not have it - by any route.
        """
        self.project.publication_status = PublicationStatus.PUBLISHED
        self.project.save()
        self.assertFalse(visible(self.project))

    def test_public_pages_refuse_an_unpublished_record(self):
        response = self.client.get(
            reverse("core:public_program", args=[self.program.slug])
        )
        self.assertEqual(response.status_code, 404)

    def test_public_pages_serve_a_published_record(self):
        self.publish_chain(self.program)
        response = self.client.get(
            reverse("core:public_program", args=[self.program.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.program.title)

    def test_a_withdrawn_parent_takes_the_child_page_offline(self):
        self.publish_chain(self.program, self.project)
        url = reverse("core:public_project", args=[self.project.slug])
        self.assertEqual(self.client.get(url).status_code, 200)

        self.program.unpublish(self.publisher)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_public_statistics_count_published_records_only(self):
        figures = public_statistics()
        self.assertEqual(figures["outcomes"], 5)
        self.assertEqual(figures["programs"], 0)

        self.publish_chain(self.program, self.project, self.sub_project,
                           self.activity)
        figures = public_statistics()
        self.assertEqual(figures["programs"], 1)
        self.assertEqual(figures["projects"], 1)
        self.assertEqual(figures["sub_projects"], 1)
        self.assertEqual(figures["activities"], 1)

    def test_public_pages_address_records_by_slug_not_by_database_id(self):
        self.publish_chain(self.program)

        listing = self.client.get(reverse("core:public_programs"))
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn(f"/{self.program.pk}/", listing.content.decode())

        outcome = self.client.get(
            reverse("core:public_outcome", args=["excellence-in-local-governance"])
        )
        body = outcome.content.decode()
        self.assertIn(self.program.slug, body)
        self.assertNotIn(f"/program/{self.program.pk}/", body)

    def test_the_outcome_page_lists_all_five_outcomes(self):
        response = self.client.get(reverse("core:public_programs"))
        for outcome in OrganizationalOutcome:
            self.assertContains(response, outcome.label)


class PublicDocumentTests(PPATestCase):
    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        self.document = SupportingDocument.objects.create(
            title="Regional summary",
            kind=DocumentKind.REPORT,
            program=self.program,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile("summary.txt", b"A clean regional summary."),
        )
        screening.screen_document(self.document)

    def url(self):
        return reverse("core:public_document_file", args=[self.document.public_token])

    def test_an_internal_document_is_not_served_publicly(self):
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_an_approved_but_unpublished_document_is_not_served(self):
        self.document.approve(self.reviewer)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_a_published_document_is_served(self):
        self.clear_for_release(self.document)
        self.publish_chain(self.program)
        self.document.refresh_from_db()

        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content),
                         b"A clean regional summary.")
        close_response(response)

    def test_withdrawing_the_parent_stops_the_download(self):
        self.clear_for_release(self.document)
        self.publish_chain(self.program)
        served = self.client.get(self.url())
        self.assertEqual(served.status_code, 200)
        close_response(served)

        self.program.unpublish(self.publisher)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_the_internal_file_needs_a_signed_in_member_of_staff(self):
        url = reverse("programs:document_download", args=[self.document.pk])
        response = self.client.get(url)
        self.assertIn(response.status_code, (302, 403))

        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.encoder)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        close_response(response)


# ---------------------------------------------------------------------------
# Who may do what
# ---------------------------------------------------------------------------


class PermissionTests(PPATestCase):
    def test_the_three_capabilities_are_held_by_different_roles(self):
        self.assertTrue(self.encoder.can_encode_ppa)
        self.assertFalse(self.encoder.can_review_ppa)
        self.assertFalse(self.encoder.can_publish_ppa)

        self.assertTrue(self.reviewer.can_review_ppa)
        self.assertFalse(self.reviewer.can_publish_ppa)

        self.assertTrue(self.publisher.can_publish_ppa)

        self.assertFalse(self.viewer.can_encode_ppa)
        self.assertFalse(self.viewer.can_review_ppa)

    def test_an_encoder_cannot_publish_over_http(self):
        self.program.approve(self.reviewer)
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("programs:publish", args=["program", self.program.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.program.refresh_from_db()
        self.assertFalse(self.program.is_published)

    def test_a_reviewer_cannot_publish_over_http(self):
        self.program.approve(self.reviewer)
        self.client.force_login(self.reviewer)
        response = self.client.post(
            reverse("programs:publish", args=["program", self.program.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_an_encoder_cannot_approve_content(self):
        self.program.submit_for_review(self.encoder)
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("programs:decide", args=["program", self.program.pk]),
            {"decision": "approve"},
        )
        self.assertEqual(response.status_code, 403)

    def test_a_viewer_cannot_reach_the_review_queue(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("programs:queue")).status_code, 403)

    def test_workflow_endpoints_refuse_get(self):
        """A state change must not be something a prefetching browser can cause."""
        self.client.force_login(self.publisher)
        for name in ("submit", "publish", "unpublish", "archive"):
            with self.subTest(action=name):
                response = self.client.get(
                    reverse(f"programs:{name}", args=["program", self.program.pk])
                )
                self.assertEqual(response.status_code, 405)


class ReviewScreenTests(PPATestCase):
    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        self.document = SupportingDocument.objects.create(
            title="Validation report",
            kind=DocumentKind.REPORT,
            program=self.program,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile(
                "report.txt", b"STRICTLY CONFIDENTIAL\nTIN 123-456-789-000"
            ),
        )
        screening.screen_document(self.document)
        self.url = reverse("programs:document_review", args=[self.document.pk])

    def test_the_review_screen_shows_the_result_and_the_warnings(self):
        self.client.force_login(self.reviewer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "High risk")
        self.assertContains(response, "Taxpayer Identification Number")

    def test_the_review_screen_does_not_reprint_the_number_it_warns_about(self):
        self.client.force_login(self.reviewer)
        response = self.client.get(self.url)
        self.assertNotContains(response, "123-456-789-000")

    def test_a_high_risk_file_cannot_be_approved_without_acknowledgement(self):
        self.client.force_login(self.reviewer)
        response = self.client.post(self.url, {"decision": "approve", "comments": ""})
        self.assertEqual(response.status_code, 200)
        self.document.refresh_from_db()
        self.assertNotEqual(self.document.status, DocumentStatus.APPROVED)

    def test_a_high_risk_file_may_be_approved_once_the_reviewer_confirms(self):
        self.client.force_login(self.reviewer)
        self.client.post(self.url, {
            "decision": "approve",
            "comments": "Checked; the TIN is the Division's own, on the header.",
            "acknowledge_risk": "on",
        })
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, DocumentStatus.APPROVED)
        self.assertEqual(self.document.reviewed_by, self.reviewer)

    def test_a_rejection_needs_a_reason(self):
        self.client.force_login(self.reviewer)
        self.client.post(self.url, {"decision": "reject", "comments": ""})
        self.document.refresh_from_db()
        self.assertNotEqual(self.document.status, DocumentStatus.REJECTED)

    def test_an_encoder_may_read_the_screening_but_not_decide(self):
        self.client.force_login(self.encoder)
        self.assertEqual(self.client.get(self.url).status_code, 200)

        response = self.client.post(self.url, {"decision": "approve"})
        self.assertEqual(response.status_code, 403)


class UploadFormTests(PPATestCase):
    """
    The upload and the create-child forms, driven the way a browser drives
    them.

    Both of these are regressions. `GovModelForm` reads `self.errors` in its
    constructor so it can mark invalid inputs, which validates the form there
    and then - so anything a view or a form sets *after* `super().__init__()`
    is set too late to be seen by validation. Calling the model layer directly,
    as the rest of this file mostly does, never exercises that; only posting to
    the view does.
    """

    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.client.force_login(self.encoder)

    def pdf(self, text="A clean regional summary."):
        """
        A minimal, uncompressed PDF.

        Built by hand rather than kept as a fixture because the point is
        the upload path, and because .txt is not one of the file types the
        module accepts - so the earlier tests here, which write .txt
        straight to the model, cannot exercise the form at all.
        """
        content = f"BT /F1 11 Tf 40 760 Td ({text}) Tj ET"
        body = "".join([
            "%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
            f"2 0 obj\n<< /Length {len(content)} >>\nstream\n",
            content,
            "\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n",
        ]).encode("latin-1")
        return SimpleUploadedFile("report.pdf", body, content_type="application/pdf")

    def test_uploading_through_the_form_attaches_the_record(self):
        response = self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Regional summary",
                "kind": DocumentKind.REPORT,
                "description": "",
                "files": self.pdf(),
                "acknowledge": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        document = SupportingDocument.objects.get(title="Regional summary")
        self.assertEqual(document.owner, self.program)
        self.assertEqual(document.uploaded_by, self.encoder)
        self.assertTrue(document.is_screened)

    def test_an_upload_must_be_acknowledged(self):
        response = self.client.post(
            reverse("programs:document_upload", args=["activity", self.activity.pk]),
            {"title": "Unchecked", "kind": DocumentKind.OTHER, "files": self.pdf()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SupportingDocument.objects.filter(title="Unchecked").exists())

    def test_only_the_listed_file_types_are_accepted(self):
        response = self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Spreadsheet of sorts",
                "kind": DocumentKind.OTHER,
                "files": SimpleUploadedFile("notes.txt", b"plain text"),
                "acknowledge": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SupportingDocument.objects.filter(title__startswith="Spread").exists())

    def photo(self, name="site.jpg", pixel=b"\xff\xd8\xff\xdb\x00photo\xff\xd9"):
        """
        A stand-in photograph.

        Not a real JPEG - the screening reads what it can and says so when it
        cannot, which is the behaviour under test here. What matters is the
        extension, because that is what decides `is_image` and therefore what
        the public gallery shows.
        """
        return SimpleUploadedFile(name, pixel, content_type="image/jpeg")

    def test_several_photographs_upload_in_one_go(self):
        """
        One form submission, one row per file, all attached to the record.

        The thing this protects is the office's actual habit: photographs
        arrive by the memory card, and before this the encoder filled in the
        same form once per picture - which is how half of them never got
        filed at all.
        """
        response = self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Turnover ceremony",
                "kind": DocumentKind.PHOTO,
                "description": "",
                "files": [self.photo("one.jpg"), self.photo("two.jpg"),
                          self.photo("three.jpg")],
                "acknowledge": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        photographs = list(self.program.documents.photographs())
        self.assertEqual(len(photographs), 3)
        for photograph in photographs:
            self.assertEqual(photograph.owner, self.program)
            self.assertEqual(photograph.uploaded_by, self.encoder)
            self.assertTrue(photograph.is_screened)

        # Numbered in selection order, and titled so a reviewer can tell them
        # apart in a queue.
        self.assertEqual(
            [photograph.display_order for photograph in photographs], [1, 2, 3]
        )
        self.assertEqual(
            [photograph.title for photograph in photographs],
            ["Turnover ceremony (1)", "Turnover ceremony (2)",
             "Turnover ceremony (3)"],
        )

    def test_a_single_upload_keeps_its_title_unnumbered(self):
        self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Regional summary",
                "kind": DocumentKind.REPORT,
                "description": "",
                "files": self.pdf(),
                "acknowledge": "on",
            },
        )
        self.assertTrue(
            SupportingDocument.objects.filter(title="Regional summary").exists()
        )

    def test_a_caption_per_photograph_becomes_its_description(self):
        self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Validation visit",
                "kind": DocumentKind.PHOTO,
                "description": "Shared description",
                "files": [self.photo("one.jpg"), self.photo("two.jpg")],
                "file_caption": ["Opening programme", ""],
                "acknowledge": "on",
            },
        )
        photographs = list(self.program.documents.photographs())
        self.assertEqual(photographs[0].description, "Opening programme")
        # No caption typed for the second, so the shared description stands.
        self.assertEqual(photographs[1].description, "Shared description")

    def test_one_bad_file_stops_the_whole_batch(self):
        """
        Nothing is stored unless everything passes.

        A partial batch is worse than a refused one: the encoder sees a
        success message, the office sees four of five pictures, and nobody
        finds out which one is missing until somebody counts.
        """
        response = self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Mixed batch",
                "kind": DocumentKind.PHOTO,
                "description": "",
                "files": [self.photo("good.jpg"),
                          SimpleUploadedFile("script.exe", b"MZ")],
                "acknowledge": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            SupportingDocument.objects.filter(title__startswith="Mixed").exists()
        )

    def test_the_gallery_can_be_rearranged(self):
        self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Ceremony",
                "kind": DocumentKind.PHOTO,
                "description": "",
                "files": [self.photo("one.jpg"), self.photo("two.jpg"),
                          self.photo("three.jpg")],
                "acknowledge": "on",
            },
        )
        photographs = list(self.program.documents.photographs())
        reversed_order = list(reversed([p.pk for p in photographs]))

        response = self.client.post(
            reverse("programs:photo_arrange", args=["program", self.program.pk]),
            {"order": ",".join(str(pk) for pk in reversed_order)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            [p.pk for p in self.program.documents.photographs()], reversed_order
        )

    def test_rearranging_refuses_a_document_from_another_record(self):
        """
        The submitted list is checked against this record's own pictures.

        Otherwise a stray identifier - mistyped, or supplied on purpose -
        would renumber a file belonging to a programme the person posting it
        may not even be able to see.
        """
        self.client.post(
            reverse("programs:document_upload", args=["program", self.program.pk]),
            {
                "title": "Ceremony",
                "kind": DocumentKind.PHOTO,
                "description": "",
                "files": [self.photo("one.jpg"), self.photo("two.jpg")],
                "acknowledge": "on",
            },
        )
        self.client.post(
            reverse("programs:document_upload", args=["activity", self.activity.pk]),
            {
                "title": "Elsewhere",
                "kind": DocumentKind.PHOTO,
                "description": "",
                "files": [self.photo("other.jpg")],
                "acknowledge": "on",
            },
        )
        mine = list(self.program.documents.photographs())
        theirs = self.activity.documents.photographs().first()

        before = [photograph.display_order for photograph in mine]
        self.client.post(
            reverse("programs:photo_arrange", args=["program", self.program.pk]),
            {"order": f"{theirs.pk},{mine[0].pk},{mine[1].pk}"},
        )
        self.program.refresh_from_db()
        self.assertEqual(
            [p.display_order for p in self.program.documents.photographs()], before
        )
        theirs.refresh_from_db()
        self.assertEqual(theirs.display_order, 1)


    def test_creating_a_child_through_the_form_keeps_its_parent(self):
        """
        The parent control is disabled, so a browser does not submit it. The
        form must supply it anyway.
        """
        response = self.client.post(
            reverse("programs:create_child",
                    args=["program", self.program.pk, "project"]),
            {"title": "New project", "description": "", "status": ProgramStatus.PENDING},
        )
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(title="New project")
        self.assertEqual(project.program, self.program)

    def test_creating_an_activity_under_a_sub_project_parents_it_correctly(self):
        response = self.client.post(
            reverse("programs:create_child",
                    args=["sub-project", self.sub_project.pk, "activity"]),
            {"title": "New activity", "description": "",
             "status": ProgramStatus.COMPLETED},
        )
        self.assertEqual(response.status_code, 302)
        activity = Activity.objects.get(title="New activity")
        self.assertEqual(activity.sub_project, self.sub_project)
        self.assertIsNone(activity.project)


class WithdrawalTests(PPATestCase):
    """Withdrawal has to work even when the bytes cannot be deleted."""

    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        self.document = SupportingDocument.objects.create(
            title="Regional summary", kind=DocumentKind.REPORT,
            program=self.program, uploaded_by=self.encoder,
            file=SimpleUploadedFile("summary.txt", b"A clean regional summary."),
        )
        screening.screen_document(self.document)
        self.clear_for_release(self.document)
        self.publish_chain(self.program)
        self.document.refresh_from_db()

    def test_a_file_that_cannot_be_deleted_is_still_taken_offline(self):
        """
        On Windows a file held open by a request in flight cannot be removed.
        A withdrawal that gave up at that point would leave the document
        published and the file still being served, which is the one outcome a
        withdrawal must never produce.
        """
        from unittest import mock

        storage = self.document.public_file.storage
        with mock.patch.object(storage, "delete", side_effect=OSError("locked")):
            with self.assertLogs("lgmed.programs", level="ERROR"):
                self.document.withdraw(self.publisher)

        self.document.refresh_from_db()
        self.assertEqual(self.document.status, DocumentStatus.WITHDRAWN)
        self.assertFalse(self.document.public_file)
        self.assertIsNone(self.document.public_url)

        # And nothing serves it, because nothing ever served it from disk.
        response = self.client.get(
            reverse("core:public_document_file", args=[self.document.public_token])
        )
        self.assertEqual(response.status_code, 404)


class DocumentDeletionTests(PPATestCase):
    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        self.document = SupportingDocument.objects.create(
            title="Regional summary", kind=DocumentKind.REPORT,
            program=self.program, uploaded_by=self.encoder,
            file=SimpleUploadedFile("summary.txt", b"A clean regional summary."),
        )
        screening.screen_document(self.document)
        self.url = reverse("programs:document_delete", args=[self.document.pk])

    def test_an_encoder_may_delete_a_file_uploaded_by_mistake(self):
        self.client.force_login(self.encoder)
        self.client.post(self.url)
        self.assertFalse(SupportingDocument.objects.filter(pk=self.document.pk).exists())

    def test_an_encoder_cannot_delete_a_published_file(self):
        """
        Deleting is not a back door around the publisher: taking a file off the
        public website is an administrator's decision.
        """
        self.clear_for_release(self.document)
        self.publish_chain(self.program)
        self.document.refresh_from_db()

        self.client.force_login(self.encoder)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(SupportingDocument.objects.filter(pk=self.document.pk).exists())


class PreviewTests(PPATestCase):
    def test_a_preview_shows_cleared_children_only(self):
        """
        A preview promising a page the public will not get is worse than none.
        """
        self.project.approve(self.reviewer)
        draft = Project.objects.create(
            title="Not yet cleared project", program=self.program,
            created_by=self.encoder,
        )

        self.client.force_login(self.encoder)
        response = self.client.get(
            reverse("programs:preview", args=["program", self.program.pk])
        )
        self.assertContains(response, self.project.title)
        self.assertNotContains(response, draft.title)


class WorkbenchPageTests(PPATestCase):
    def test_the_workbench_renders_the_whole_tree(self):
        self.client.force_login(self.encoder)
        response = self.client.get(reverse("programs:list"))
        self.assertEqual(response.status_code, 200)
        for record in (self.program, self.project, self.sub_project, self.activity):
            self.assertContains(response, record.title)

    def test_the_workbench_names_all_five_outcomes(self):
        self.client.force_login(self.encoder)
        response = self.client.get(reverse("programs:list"))
        for outcome in OrganizationalOutcome:
            self.assertContains(response, outcome.label)

    def test_every_level_has_a_working_detail_page(self):
        self.client.force_login(self.encoder)
        for level, record in (
            ("program", self.program), ("project", self.project),
            ("sub-project", self.sub_project), ("activity", self.activity),
        ):
            with self.subTest(level=level):
                response = self.client.get(
                    reverse("programs:detail", args=[level, record.pk])
                )
                self.assertEqual(response.status_code, 200)

    def test_an_unknown_level_is_a_404(self):
        self.client.force_login(self.encoder)
        response = self.client.get("/app/programs/programme/1/")
        self.assertEqual(response.status_code, 404)

    def test_the_preview_renders_the_public_page_before_publication(self):
        self.client.force_login(self.encoder)
        response = self.client.get(
            reverse("programs:preview", args=["program", self.program.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preview")
        self.assertContains(response, self.program.title)

    def test_creating_a_child_requires_a_parent_that_may_hold_it(self):
        self.client.force_login(self.encoder)
        response = self.client.get(
            reverse("programs:create_child",
                    args=["program", self.program.pk, "activity"])
        )
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# The authority to publish
# ---------------------------------------------------------------------------


class PublicationAuthorityTests(PPATestCase):
    """
    A file reaches the public website under a written authority or not at all.

    Approval says the content is fit to be seen. The memorandum is the office's
    written decision that it *be* seen. These tests hold the line that both are
    required, and that neither can be quietly substituted for the other.
    """

    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        self.authority = PublicationAuthority.objects.create(
            reference="LGMED Memorandum No. 2026-014",
            title="Authority to publish the 2026 SGLG regional results",
            approved_on=TODAY - datetime.timedelta(days=7),
            approved_by="Regional Director",
            created_by=self.publisher,
        )
        self.document = SupportingDocument.objects.create(
            title="Regional summary", kind=DocumentKind.REPORT,
            program=self.program, uploaded_by=self.encoder,
            file=SimpleUploadedFile("summary.txt", b"A clean regional summary."),
        )
        screening.screen_document(self.document)

    # -- the control itself ------------------------------------------------

    def test_an_approved_file_without_a_memorandum_cannot_be_published(self):
        self.document.approve(self.reviewer)
        self.publish_chain(self.program)
        self.document.refresh_from_db()

        self.assertFalse(self.document.may_be_released)
        self.assertIn("No memorandum", self.document.release_blocker)
        with self.assertRaises(ValidationError):
            self.document.publish(self.publisher)

    def test_a_memorandum_lets_the_file_be_published(self):
        self.document.authority = self.authority
        self.document.approve(self.reviewer)
        self.publish_chain(self.program)
        self.document.refresh_from_db()

        self.assertTrue(self.document.may_be_released)
        self.assertIsNone(self.document.release_blocker)
        self.assertEqual(self.document.status, DocumentStatus.PUBLISHED)
        self.assertTrue(self.document.public_file)

    def test_a_memorandum_alone_is_not_enough(self):
        """The authority does not substitute for the review."""
        self.document.authority = self.authority
        self.document.save()
        self.publish_chain(self.program)
        self.document.refresh_from_db()

        self.assertFalse(self.document.may_be_released)
        self.assertIn("not yet approved", self.document.release_blocker)
        with self.assertRaises(ValidationError):
            self.document.publish(self.publisher)

    def test_a_withdrawn_memorandum_cannot_authorise_a_release(self):
        self.document.authority = self.authority
        self.document.approve(self.reviewer)
        self.publish_chain(self.program)
        self.document.refresh_from_db()
        self.document.status = DocumentStatus.APPROVED
        self.document.save()

        self.authority.is_active = False
        self.authority.save()
        self.document.refresh_from_db()

        self.assertFalse(self.document.may_be_released)
        self.assertIn("withdrawn", self.document.release_blocker.lower())
        with self.assertRaises(ValidationError):
            self.document.publish(self.publisher)

    def test_an_expired_memorandum_cannot_authorise_a_release(self):
        self.authority.effective_until = TODAY - datetime.timedelta(days=1)
        self.authority.save()
        self.document.authority = self.authority
        self.document.approve(self.reviewer)

        self.assertFalse(self.authority.is_in_force())
        self.assertEqual(self.authority.status_label, "Expired")
        with self.assertRaises(ValidationError):
            self.document.publish(self.publisher)

    def test_a_memorandum_not_yet_in_effect_cannot_authorise_a_release(self):
        self.authority.effective_from = TODAY + datetime.timedelta(days=3)
        self.authority.save()
        self.document.authority = self.authority
        self.document.approve(self.reviewer)

        self.assertEqual(self.authority.status_label, "Not yet in effect")
        with self.assertRaises(ValidationError):
            self.document.publish(self.publisher)

    def test_an_authority_cannot_end_before_it_starts(self):
        authority = PublicationAuthority(
            reference="X-1", title="t", approved_on=TODAY,
            approved_by="Director",
            effective_from=TODAY, effective_until=TODAY - datetime.timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            authority.clean()

    # -- publishing a record around it -------------------------------------

    def test_publishing_a_record_holds_back_unauthorised_files(self):
        """
        The content goes live; the file without a memorandum does not. Holding
        the whole record back would punish the description for the paperwork.
        """
        authorised = self.document
        authorised.authority = self.authority
        authorised.approve(self.reviewer)

        orphan = SupportingDocument.objects.create(
            title="Annex without a memorandum", kind=DocumentKind.OTHER,
            program=self.program, uploaded_by=self.encoder,
            file=SimpleUploadedFile("annex.txt", b"An annex."),
        )
        screening.screen_document(orphan)
        orphan.approve(self.reviewer)

        self.program.approve(self.reviewer)
        outcome = self.program.publish(self.publisher)

        authorised.refresh_from_db()
        orphan.refresh_from_db()

        self.assertTrue(self.program.is_published)
        self.assertEqual(authorised.status, DocumentStatus.PUBLISHED)
        self.assertEqual(orphan.status, DocumentStatus.APPROVED)
        self.assertFalse(orphan.public_file)
        self.assertEqual([d.pk for d in outcome["released"]], [authorised.pk])
        self.assertEqual([d.pk for d in outcome["held"]], [orphan.pk])

    def test_the_publisher_is_told_which_files_were_held_back(self):
        self.document.approve(self.reviewer)
        self.program.approve(self.reviewer)

        self.client.force_login(self.publisher)
        response = self.client.post(
            reverse("programs:publish", args=["program", self.program.pk]),
            follow=True,
        )
        text = " ".join(str(m) for m in response.context["messages"])
        self.assertIn("Regional summary", text)
        self.assertIn("memorandum", text.lower())

    def test_the_public_file_is_unreachable_without_an_authority(self):
        self.document.approve(self.reviewer)
        self.publish_chain(self.program)
        self.document.refresh_from_db()

        response = self.client.get(
            reverse("core:public_document_file", args=[self.document.public_token])
        )
        self.assertEqual(response.status_code, 404)

    # -- recording and citing one through the interface --------------------

    def test_a_reviewer_may_cite_a_memorandum_while_approving(self):
        self.client.force_login(self.reviewer)
        self.client.post(
            reverse("programs:document_review", args=[self.document.pk]),
            {"decision": "approve", "authority": self.authority.pk, "comments": ""},
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, DocumentStatus.APPROVED)
        self.assertEqual(self.document.authority, self.authority)

    def test_a_memorandum_can_be_cited_after_approval(self):
        self.document.approve(self.reviewer)
        self.publish_chain(self.program)

        self.client.force_login(self.reviewer)
        self.client.post(
            reverse("programs:document_authority", args=[self.document.pk]),
            {"authority": self.authority.pk},
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.authority, self.authority)
        self.assertTrue(self.document.may_be_released)
        # The programme is already live, so the file is now one click away.
        self.assertTrue(self.document.is_awaiting_release)

    def test_a_withdrawn_memorandum_is_not_offered(self):
        self.authority.is_active = False
        self.authority.save()

        form = DocumentAuthorityForm(data={"authority": self.authority.pk})
        self.assertFalse(form.is_valid())

    def test_an_encoder_cannot_record_a_memorandum(self):
        self.client.force_login(self.encoder)
        self.assertEqual(
            self.client.get(reverse("programs:authority_create")).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("programs:authority_list")).status_code, 403
        )

    def test_an_encoder_cannot_cite_a_memorandum(self):
        self.document.approve(self.reviewer)
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("programs:document_authority", args=[self.document.pk]),
            {"authority": self.authority.pk},
        )
        self.assertEqual(response.status_code, 403)
        self.document.refresh_from_db()
        self.assertIsNone(self.document.authority)

    def test_the_authority_pages_render(self):
        self.document.authority = self.authority
        self.document.approve(self.reviewer)

        self.client.force_login(self.reviewer)
        for url in (
            reverse("programs:authority_list"),
            reverse("programs:authority_detail", args=[self.authority.pk]),
            reverse("programs:authority_update", args=[self.authority.pk]),
            reverse("programs:authority_create"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        detail = self.client.get(
            reverse("programs:authority_detail", args=[self.authority.pk])
        )
        self.assertContains(detail, self.document.title)

    def test_the_review_screen_says_what_is_missing(self):
        self.document.approve(self.reviewer)
        self.client.force_login(self.reviewer)
        response = self.client.get(
            reverse("programs:document_review", args=[self.document.pk])
        )
        self.assertContains(response, "Authority to publish")
        self.assertContains(response, "No memorandum")

    def test_the_public_page_cites_the_authority(self):
        self.document.authority = self.authority
        self.document.approve(self.reviewer)
        self.publish_chain(self.program)

        response = self.client.get(self.program.public_url)
        self.assertContains(response, self.authority.reference)

    def test_an_authority_in_use_cannot_be_deleted(self):
        """PROTECT, so the trail of what was released under it survives."""
        from django.db.models import ProtectedError

        self.document.authority = self.authority
        self.document.save()
        with self.assertRaises(ProtectedError):
            self.authority.delete()


class LateAttachmentTests(PPATestCase):
    """
    Files added to a record that is already on the public website.

    This is the ordinary case, not an edge one: a programme is published once
    and then added to for months, so most photographs and reports are filed
    after it went live. Before this was handled they reached APPROVED and
    stopped there - the only route out was to unpublish the whole programme and
    republish it, which takes everything else offline for the sake of one file.
    """

    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        # The programme goes live first, with nothing attached.
        self.publish_chain(self.program)

        self.photo = SupportingDocument.objects.create(
            title="Photographs of the orientation",
            kind=DocumentKind.PHOTO,
            program=self.program,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff not really a jpeg"),
        )
        screening.screen_document(self.photo)

    def test_a_file_approved_after_publication_is_ready_to_go_out(self):
        self.clear_for_release(self.photo)

        self.assertTrue(self.photo.is_awaiting_release)
        self.assertIsNone(self.photo.release_blocker)

    def test_a_publisher_can_release_it_without_touching_the_record(self):
        self.clear_for_release(self.photo)

        self.client.force_login(self.publisher)
        self.client.post(reverse("programs:document_publish", args=[self.photo.pk]))

        self.photo.refresh_from_db()
        self.program.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.PUBLISHED)
        self.assertTrue(self.photo.public_file)
        # The programme was never disturbed.
        self.assertTrue(self.program.is_published)
        self.assertIsNone(self.program.unpublished_at)

    def test_the_released_file_is_served_to_the_public(self):
        self.clear_for_release(self.photo)
        self.client.force_login(self.publisher)
        self.client.post(reverse("programs:document_publish", args=[self.photo.pk]))
        self.photo.refresh_from_db()

        self.client.logout()
        response = self.client.get(self.photo.public_url)
        self.assertEqual(response.status_code, 200)
        close_response(response)

    def test_the_review_screen_offers_the_publisher_the_button(self):
        self.clear_for_release(self.photo)
        self.client.force_login(self.publisher)
        response = self.client.get(
            reverse("programs:document_review", args=[self.photo.pk])
        )
        self.assertContains(response, "Publish this file")

    def test_the_record_page_lists_what_is_waiting(self):
        self.clear_for_release(self.photo)
        self.client.force_login(self.publisher)
        response = self.client.get(
            reverse("programs:detail", args=["program", self.program.pk])
        )
        self.assertContains(response, "ready to publish")
        self.assertContains(response, self.photo.title)

    # -- the guards are not relaxed to make this work ----------------------

    def test_an_encoder_cannot_release_a_file(self):
        self.clear_for_release(self.photo)
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("programs:document_publish", args=[self.photo.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.APPROVED)

    def test_a_reviewer_cannot_release_a_file(self):
        self.clear_for_release(self.photo)
        self.client.force_login(self.reviewer)
        response = self.client.post(
            reverse("programs:document_publish", args=[self.photo.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_a_file_without_a_memorandum_is_not_ready(self):
        self.photo.approve(self.reviewer)
        self.assertFalse(self.photo.is_awaiting_release)
        with self.assertRaises(ValidationError):
            self.photo.publish(self.publisher)

    def test_an_unapproved_file_is_not_ready(self):
        self.photo.authority = self.authority
        self.photo.save()
        self.assertFalse(self.photo.is_awaiting_release)
        with self.assertRaises(ValidationError):
            self.photo.publish(self.publisher)

    def test_a_file_under_an_unpublished_record_cannot_be_released_alone(self):
        """
        Releasing one file must not become a way around an unpublished record.
        """
        draft = Program.objects.create(title="Not published", created_by=self.encoder)
        document = SupportingDocument.objects.create(
            title="Annex", kind=DocumentKind.OTHER, program=draft,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile("annex.txt", b"An annex."),
        )
        screening.screen_document(document)
        self.clear_for_release(document)

        self.assertFalse(document.is_awaiting_release)
        self.assertIn("not on the public website", document.release_blocker)
        with self.assertRaises(ValidationError):
            document.publish(self.publisher)

    # -- taking one file back down -----------------------------------------

    def test_one_file_can_be_withdrawn_without_unpublishing_the_record(self):
        self.clear_for_release(self.photo)
        self.client.force_login(self.publisher)
        self.client.post(reverse("programs:document_publish", args=[self.photo.pk]))
        self.photo.refresh_from_db()
        public = Path(self.photo.public_file.path)

        self.client.post(reverse("programs:document_withdraw", args=[self.photo.pk]))

        self.photo.refresh_from_db()
        self.program.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.WITHDRAWN)
        self.assertFalse(public.exists())
        self.assertTrue(self.program.is_published)

    def test_an_encoder_cannot_withdraw_a_file(self):
        self.clear_for_release(self.photo)
        self.client.force_login(self.publisher)
        self.client.post(reverse("programs:document_publish", args=[self.photo.pk]))

        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("programs:document_withdraw", args=[self.photo.pk])
        )
        self.assertEqual(response.status_code, 403)


class RepublishingTests(PPATestCase):
    """
    Publish, take down, publish again - each one confirmed action.

    Withdrawal used to be a dead end. The status went to WITHDRAWN and every
    predicate in the module read that as "not approved", so the only way back
    onto the website was a second trip through the reviewer's decision form
    followed by a separate publish: several confirmations for something the
    office had already decided once. The approval had never been revoked -
    `withdraw` does not touch it - so the state was also simply wrong about
    what had happened.

    These tests hold the fix in place from both ends: a withdrawn file is
    offered again as itself, and none of what it carries is lost on the way.
    """

    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        self.publish_chain(self.program)

        self.photo = SupportingDocument.objects.create(
            title="Photographs of the orientation",
            description="Taken at the municipal hall.",
            kind=DocumentKind.PHOTO,
            program=self.program,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff not really a jpeg"),
        )
        screening.screen_document(self.photo)
        self.clear_for_release(self.photo)

    def publish(self):
        return self.client.post(
            reverse("programs:document_publish", args=[self.photo.pk])
        )

    def withdraw(self):
        return self.client.post(
            reverse("programs:document_withdraw", args=[self.photo.pk])
        )

    # -- the round trip ----------------------------------------------------

    def test_a_withdrawn_file_can_be_published_again_in_one_action(self):
        """Publish, take down, publish again: three posts, no re-review."""
        self.client.force_login(self.publisher)

        self.publish()
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.PUBLISHED)

        self.withdraw()
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.WITHDRAWN)

        # The whole of the fix: no decision form in between.
        self.publish()
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.PUBLISHED)
        self.assertTrue(self.photo.public_file)
        self.assertTrue(Path(self.photo.public_file.path).exists())

    def test_a_withdrawn_file_is_offered_for_release(self):
        self.client.force_login(self.publisher)
        self.publish()
        self.withdraw()
        self.photo.refresh_from_db()

        self.assertTrue(self.photo.is_awaiting_release)
        self.assertIsNone(self.photo.release_blocker)
        self.assertTrue(self.photo.may_be_released)

    def test_the_record_page_offers_a_withdrawn_file_back(self):
        self.client.force_login(self.publisher)
        self.publish()
        self.withdraw()

        response = self.client.get(
            reverse("programs:detail", args=["program", self.program.pk])
        )
        self.assertIn(self.photo, response.context["ready_documents"])
        self.assertContains(response, "Publish again")

    def test_the_record_page_offers_a_published_file_a_way_down(self):
        """One click from the record, rather than a trip through review."""
        self.client.force_login(self.publisher)
        self.publish()

        response = self.client.get(
            reverse("programs:detail", args=["program", self.program.pk])
        )
        self.assertIn(self.photo, response.context["published_documents"])
        self.assertContains(
            response,
            reverse("programs:document_withdraw", args=[self.photo.pk]),
        )

    # -- what must survive a withdrawal ------------------------------------

    def test_withdrawing_destroys_the_public_copy_and_nothing_else(self):
        """
        The file, its details and its trail are not what comes down. Only the
        copy in the served directory is, because that is the thing that made it
        public.
        """
        self.client.force_login(self.publisher)
        self.publish()
        self.photo.refresh_from_db()
        internal = Path(self.photo.file.path)
        public = Path(self.photo.public_file.path)

        self.withdraw()
        self.photo.refresh_from_db()

        self.assertFalse(public.exists())
        self.assertTrue(internal.exists())
        self.assertEqual(SupportingDocument.objects.filter(pk=self.photo.pk).count(), 1)
        self.assertEqual(self.photo.title, "Photographs of the orientation")
        self.assertEqual(self.photo.description, "Taken at the municipal hall.")
        self.assertEqual(self.photo.kind, DocumentKind.PHOTO)
        self.assertEqual(self.photo.uploaded_by, self.encoder)
        self.assertEqual(self.photo.reviewed_by, self.reviewer)
        self.assertEqual(self.photo.authority, self.authority)
        self.assertEqual(self.photo.program, self.program)

    def test_republishing_keeps_the_reviewer_who_approved_it(self):
        """
        Republishing is a publication act, not a review. Nothing about who
        cleared the file, or when, may be rewritten by it.
        """
        self.client.force_login(self.publisher)
        self.publish()
        self.photo.refresh_from_db()
        reviewed_at, reviewed_by = self.photo.reviewed_at, self.photo.reviewed_by

        self.withdraw()
        self.publish()
        self.photo.refresh_from_db()

        self.assertEqual(self.photo.reviewed_at, reviewed_at)
        self.assertEqual(self.photo.reviewed_by, reviewed_by)
        self.assertEqual(self.photo.authority, self.authority)
        self.assertEqual(self.photo.published_by, self.publisher)
        self.assertIsNone(self.photo.withdrawn_at)

    def test_republishing_keeps_its_place_in_the_gallery(self):
        self.photo.display_order = 3
        self.photo.save()
        self.client.force_login(self.publisher)

        self.publish()
        self.withdraw()
        self.publish()

        self.photo.refresh_from_db()
        self.assertEqual(self.photo.display_order, 3)

    def test_the_public_page_follows_the_status_both_ways(self):
        """The internal state and the website say the same thing throughout."""
        self.client.force_login(self.publisher)
        self.publish()
        self.client.logout()
        self.assertContains(self.client.get(self.program.public_url), self.photo.title)

        self.client.force_login(self.publisher)
        self.withdraw()
        self.client.logout()
        self.assertNotContains(
            self.client.get(self.program.public_url), self.photo.title
        )

        self.client.force_login(self.publisher)
        self.publish()
        self.client.logout()
        self.assertContains(self.client.get(self.program.public_url), self.photo.title)

    # -- a repeated click --------------------------------------------------

    def test_publishing_twice_does_not_publish_twice(self):
        """
        A second post of the same button is the same decision, not a new one.
        It must not rewrite the public copy or write a second line into the
        trail.
        """
        self.client.force_login(self.publisher)
        self.publish()
        self.photo.refresh_from_db()
        name = self.photo.public_file.name
        published_at = self.photo.published_at
        before = AuditEvent.objects.filter(action=Action.PUBLISH).count()

        self.publish()

        self.photo.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.PUBLISHED)
        self.assertEqual(self.photo.public_file.name, name)
        self.assertEqual(self.photo.published_at, published_at)
        self.assertEqual(
            AuditEvent.objects.filter(action=Action.PUBLISH).count(), before
        )

    def test_withdrawing_twice_does_not_withdraw_twice(self):
        self.client.force_login(self.publisher)
        self.publish()
        self.withdraw()
        self.photo.refresh_from_db()
        withdrawn_at = self.photo.withdrawn_at
        before = AuditEvent.objects.filter(action=Action.UNPUBLISH).count()

        self.withdraw()

        self.photo.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.WITHDRAWN)
        self.assertEqual(self.photo.withdrawn_at, withdrawn_at)
        self.assertEqual(
            AuditEvent.objects.filter(action=Action.UNPUBLISH).count(), before
        )

    # -- the controls are unchanged ----------------------------------------

    def test_a_withdrawn_file_still_needs_its_memorandum(self):
        """
        Republishing is one action, not a relaxed one. Withdrawal restores the
        approval; it does not stand in for the authority.
        """
        self.client.force_login(self.publisher)
        self.publish()
        self.withdraw()

        self.photo.refresh_from_db()
        self.photo.authority = None
        self.photo.save()

        self.assertFalse(self.photo.is_awaiting_release)
        self.assertIn("memorandum", self.photo.release_blocker)
        with self.assertRaises(ValidationError):
            self.photo.publish(self.publisher)

    def test_a_withdrawn_file_under_an_unpublished_record_stays_down(self):
        self.client.force_login(self.publisher)
        self.publish()
        self.withdraw()

        self.program.unpublish(self.publisher)
        self.photo.refresh_from_db()

        self.assertFalse(self.photo.is_awaiting_release)
        with self.assertRaises(ValidationError):
            self.photo.publish(self.publisher)

    def test_a_rejected_file_is_still_a_dead_end(self):
        """
        WITHDRAWN is publication saying "not now"; REJECTED is the reviewer
        saying no. Only the first of them may be undone by a publisher.
        """
        self.client.force_login(self.publisher)
        self.publish()
        self.photo.refresh_from_db()
        self.photo.reject(self.reviewer, "Shows a face that should not be shown.")

        self.assertEqual(self.photo.status, DocumentStatus.REJECTED)
        self.assertFalse(self.photo.is_awaiting_release)
        with self.assertRaises(ValidationError):
            self.photo.publish(self.publisher)

    def test_an_encoder_cannot_republish_a_withdrawn_file(self):
        self.client.force_login(self.publisher)
        self.publish()
        self.withdraw()

        self.client.force_login(self.encoder)
        response = self.publish()

        self.assertEqual(response.status_code, 403)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.WITHDRAWN)


class RecordRepublishingTests(PPATestCase):
    """
    Taking a record down and putting it back, and what its files do.

    Two withdrawals look the same on the row and are not the same decision. A
    file that came down because its programme did is expected back when the
    programme returns - restoring twenty photographs by hand is how an office
    ends up not restoring them. A file a publisher took down on its own was a
    judgement about that file, and republishing the record must not quietly
    reverse it.
    """

    def setUp(self):
        self.override, self.root = temp_media()
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.root, True)

        self.report = SupportingDocument.objects.create(
            title="Accomplishment report",
            kind=DocumentKind.REPORT,
            program=self.program,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile("report.txt", b"An accomplishment report."),
        )
        self.photo = SupportingDocument.objects.create(
            title="Photographs of the orientation",
            kind=DocumentKind.PHOTO,
            program=self.program,
            uploaded_by=self.encoder,
            file=SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff not really a jpeg"),
        )
        for document in (self.report, self.photo):
            screening.screen_document(document)
        self.clear_for_release(self.report, self.photo)

    def test_files_that_came_down_with_the_record_go_back_up_with_it(self):
        self.publish_chain(self.program)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, DocumentStatus.PUBLISHED)

        self.program.unpublish(self.publisher)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, DocumentStatus.WITHDRAWN)
        self.assertTrue(self.report.withdrawn_with_record)

        self.program.approve(self.reviewer)
        self.program.publish(self.publisher)

        self.report.refresh_from_db()
        self.assertEqual(self.report.status, DocumentStatus.PUBLISHED)
        self.assertTrue(Path(self.report.public_file.path).exists())

    def test_a_file_taken_down_on_its_own_stays_down(self):
        """
        The publisher decided about this one file. Republishing the programme
        is not a review of that decision, so it does not undo it.
        """
        self.publish_chain(self.program)
        self.photo.refresh_from_db()
        self.photo.withdraw(self.publisher)
        self.assertFalse(self.photo.withdrawn_with_record)

        self.program.unpublish(self.publisher)
        self.program.approve(self.reviewer)
        self.program.publish(self.publisher)

        self.photo.refresh_from_db()
        self.report.refresh_from_db()
        self.assertEqual(self.photo.status, DocumentStatus.WITHDRAWN)
        self.assertFalse(self.photo.public_file)
        # ... while the file that came down with the record did come back.
        self.assertEqual(self.report.status, DocumentStatus.PUBLISHED)

    def test_a_file_held_back_on_its_own_is_still_one_click_away(self):
        """It stays down, but nothing about putting it back is hard."""
        self.publish_chain(self.program)
        self.photo.refresh_from_db()
        self.photo.withdraw(self.publisher)

        self.assertTrue(self.photo.is_awaiting_release)
        self.photo.publish(self.publisher)
        self.assertEqual(self.photo.status, DocumentStatus.PUBLISHED)

    def test_unpublishing_a_record_deletes_no_files(self):
        self.publish_chain(self.program)
        self.report.refresh_from_db()
        internal = Path(self.report.file.path)

        self.program.unpublish(self.publisher)

        self.assertTrue(internal.exists())
        self.assertEqual(self.program.documents.count(), 2)


# ---------------------------------------------------------------------------
# What the public page calls each section
# ---------------------------------------------------------------------------


class PublicHeadingTests(PPATestCase):
    """
    The headings on a public record page are the record's to name.

    The tests worth having here are about the fallback, not about the override:
    an override that did not work would be noticed the first time somebody used
    it, whereas a fallback that quietly broke would rename every page in the
    region at once.
    """

    def test_a_record_that_names_nothing_keeps_the_usual_wording(self):
        self.assertEqual(self.program.public_heading("about"), "About")
        self.assertEqual(self.program.public_heading("photographs"), "Photographs")
        self.assertEqual(self.program.public_heading("projects"), "Projects")

    def test_a_record_may_rename_its_sections(self):
        self.program.about_heading = "Legal basis"
        self.program.projects_heading = "Component projects"
        self.assertEqual(self.program.public_heading("about"), "Legal basis")
        self.assertEqual(
            self.program.public_heading("projects"), "Component projects"
        )

    def test_whitespace_is_not_a_heading(self):
        """A box someone tabbed through is blank, not a nameless section."""
        self.program.about_heading = "   "
        self.assertEqual(self.program.public_heading("about"), "About")

    def test_the_public_page_shows_the_renamed_headings(self):
        self.program.about_heading = "Legal basis"
        self.program.projects_heading = "Component projects"
        self.program.save()
        self.publish_chain(self.program, self.project)

        page = self.client.get(self.program.public_url).content.decode()

        self.assertIn("Legal basis", page)
        self.assertIn("Component projects", page)
        self.assertNotIn(">About</h2>", page)
        self.assertNotIn(">Projects</h2>", page)

    def test_the_public_page_falls_back_to_the_defaults(self):
        self.publish_chain(self.program, self.project)

        page = self.client.get(self.program.public_url).content.decode()

        self.assertIn("About", page)
        self.assertIn("Projects", page)

    def test_an_encoder_may_rename_a_heading_through_the_form(self):
        self.client.force_login(self.encoder)
        response = self.client.post(
            reverse("programs:update", args=["program", self.program.pk]),
            {
                "title": self.program.title,
                "outcome_code": self.program.outcome_code,
                "reference_number": "",
                "description": self.program.description,
                "objectives": "",
                "status": self.program.status,
                "responsible_office": self.section.pk,
                "lead_office": "",
                "focal_person": "",
                "about_heading": "Legal basis",
                "objectives_heading": "",
                "photographs_heading": "",
                "projects_heading": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.program.refresh_from_db()
        self.assertEqual(self.program.about_heading, "Legal basis")

    def test_a_heading_cannot_smuggle_markup_onto_the_public_page(self):
        """
        Free text on a public page, so the escaping is worth asserting rather
        than assuming. Django autoescapes it; this test is what notices if a
        later change marks the heading safe.
        """
        self.program.about_heading = "<script>alert(1)</script>"
        self.program.save()
        self.publish_chain(self.program)

        page = self.client.get(self.program.public_url).content.decode()

        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
