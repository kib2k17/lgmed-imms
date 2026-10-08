"""
e-SIRA tests.

Signing is tested for real. Each run makes its own certificate authority,
installs it as the "PNPKI" trust root, issues employees certificates in
PKCS#12 files, signs through the same code path the Sign button uses, and then
reads the signatures back out of the PDF and validates them cryptographically.
Nothing here mocks the signature.
"""

import datetime
import io
import shutil
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import Role, User
from audit.models import Action, AuditEvent
from core.testing import close_response

from . import stats, workflow
from .models import (
    AuditAction,
    AuditEntry,
    DigitalSignature,
    DocumentStatus,
    DocumentVersion,
    EsiraDocument,
    ImmutableRecordError,
    SignatureBox,
    SignatureStyle,
    SignerProfile,
    SigningCertificate,
    StepAction,
    StepStatus,
)
from .pdf import PageGeometry, PdfRejected, box_to_pdf_rect, images_to_pdf, inspect_pdf
from .signature_images import process_signature_image
from .signing.vault import unseal
from .verification import verify_pdf

NOW = datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# A private certificate authority standing in for DICT PNPKI
# ---------------------------------------------------------------------------


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _cert(common_name, key, issuer_name, issuer_key, *, ca, email="", days=365, start=-1):
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
            + ([x509.NameAttribute(NameOID.EMAIL_ADDRESS, email)] if email else [])
        ))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_name)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW + datetime.timedelta(days=start))
        .not_valid_after(NOW + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if ca:
        builder = builder.add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True,
        )
    else:
        builder = builder.add_extension(
            x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True,
        )
    return builder.sign(issuer_key, hashes.SHA256())


class TestPKI:
    def __init__(self, name="Test PNPKI Root CA"):
        self.name = name
        self.key = _key()
        self.cert = _cert(name, self.key, name, self.key, ca=True, days=3650)

    def issue(self, common_name, passphrase="secret", email=""):
        key = _key()
        cert = _cert(common_name, key, self.name, self.key, ca=False, email=email)
        data = pkcs12.serialize_key_and_certificates(
            common_name.encode(), key, cert, [self.cert],
            serialization.BestAvailableEncryption(passphrase.encode()),
        )
        return data, cert

    def write_root(self, directory):
        path = Path(directory) / f"{self.name.replace(' ', '-')}.pem"
        path.write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))
        return str(path)


def make_pdf(pages=2, rotate=0):
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.writer import PageObject, PdfFileWriter

    writer = PdfFileWriter()
    for _ in range(pages):
        page = PageObject(
            contents=[],
            media_box=generic.ArrayObject([generic.NumberObject(n) for n in (0, 0, 612, 792)]),
        )
        if rotate:
            page["/Rotate"] = generic.NumberObject(rotate)
        writer.insert_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def upload(name="memo.pdf", pages=2):
    return SimpleUploadedFile(name, make_pdf(pages), content_type="application/pdf")


def p12_upload(data, name="me.p12"):
    return SimpleUploadedFile(name, data, content_type="application/x-pkcs12")


TEMP_ROOT = Path(tempfile.mkdtemp(prefix="lgmed-imms-esira-test-"))
PKI = TestPKI()
ROOT_PATH = PKI.write_root(TEMP_ROOT)


@override_settings(
    PROTECTED_MEDIA_ROOT=TEMP_ROOT / "protected",
    ESIRA_PNPKI_TRUST_ROOTS=[ROOT_PATH],
    ESIRA_ALLOW_UNTRUSTED_CERTIFICATES=False,
    ESIRA_SIGNING_BACKEND="pkcs12",
    ESIRA_TSA_URL="",
    ESIRA_CHECK_REVOCATION=False,
)
class EsiraTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_ROOT / "protected", ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN,
            first_name="Divina", last_name="Chief",
        )
        cls.admin2 = User.objects.create_user(
            username="admin2", password="pw", role=Role.ADMIN,
            first_name="Second", last_name="Admin",
        )
        cls.owner = User.objects.create_user(
            username="owner", password="pw", role=Role.ENCODER,
            first_name="Olivia", last_name="Owner",
        )
        cls.signer = User.objects.create_user(
            username="signer", password="pw", role=Role.LGMED_STAFF,
            first_name="Sam", last_name="Signer",
        )
        cls.approver = User.objects.create_user(
            username="director", password="pw", role=Role.VIEWER,
            first_name="Dora", last_name="Director",
        )
        cls.outsider = User.objects.create_user(
            username="outsider", password="pw", role=Role.ENCODER,
            first_name="Otto", last_name="Outsider",
        )

    # -- helpers ------------------------------------------------------------

    def new_document(self, owner=None, pages=2):
        return workflow.create_document(
            owner or self.owner, title="Memorandum on e-SIRA", pdf_file=upload(pages=pages),
        )

    def verified_certificate(self, user, passphrase="secret"):
        data, cert = PKI.issue(user.get_display_name(), passphrase)
        record = workflow.register_certificate(
            user, pkcs12_file=p12_upload(data), passphrase=passphrase,
        )
        workflow.review_certificate(
            record, self.admin if user != self.admin else self.admin2, decision="verify",
        )
        return data

    def box(self, document, signer, page=1, x=0.1, y=0.8):
        return {"page": page, "x": x, "y": y, "width": 0.3, "height": 0.08, "signer": signer.pk}

    def credentials(self, data, passphrase="secret"):
        return {"pkcs12": data, "passphrase": passphrase}


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------


class PdfGeometryTests(TestCase):
    def test_box_to_rect_unrotated(self):
        page = PageGeometry(0, 0, 600, 800, 0)
        # Top-left quarter of the displayed page is the top-left of user space.
        self.assertEqual(box_to_pdf_rect(page, 0, 0, 0.5, 0.25), (0, 600, 300, 800))

    def test_box_to_rect_honours_crop_origin(self):
        page = PageGeometry(10, 20, 600, 800, 0)
        self.assertEqual(box_to_pdf_rect(page, 0, 0.75, 0.5, 0.25), (10, 20, 310, 220))

    def test_box_to_rect_rotated_pages(self):
        # A portrait page rotated 90 degrees shows 800 wide by 600 high.
        page = PageGeometry(0, 0, 600, 800, 90)
        self.assertEqual(box_to_pdf_rect(page, 0, 0, 0.25, 0.5), (0, 0, 300, 200))
        page = PageGeometry(0, 0, 600, 800, 180)
        self.assertEqual(box_to_pdf_rect(page, 0, 0, 0.5, 0.25), (300, 0, 600, 200))
        page = PageGeometry(0, 0, 600, 800, 270)
        self.assertEqual(box_to_pdf_rect(page, 0, 0, 0.25, 0.5), (300, 600, 600, 800))

    def test_inspect_reads_pages_and_rotation(self):
        info = inspect_pdf(make_pdf(3, rotate=90))
        self.assertEqual(info.page_count, 3)
        self.assertEqual(info.pages[0].rotate, 90)
        self.assertEqual((info.pages[0].width, info.pages[0].height), (612, 792))

    def test_inspect_refuses_what_is_not_a_pdf(self):
        with self.assertRaises(PdfRejected):
            inspect_pdf(b"hello")

    def test_scanned_images_become_one_pdf(self):
        files = []
        for colour in ("white", "grey"):
            buffer = io.BytesIO()
            Image.new("RGB", (400, 500), colour).save(buffer, "PNG")
            files.append(SimpleUploadedFile("page.png", buffer.getvalue(), content_type="image/png"))
        self.assertEqual(inspect_pdf(images_to_pdf(files)).page_count, 2)

    def test_a_non_image_is_refused_as_a_scan(self):
        with self.assertRaises(PdfRejected):
            images_to_pdf([SimpleUploadedFile("x.png", b"not an image")])


# ---------------------------------------------------------------------------
# Upload, versions and immutability
# ---------------------------------------------------------------------------


class UploadTests(EsiraTestCase):
    def test_upload_creates_a_draft_with_an_original_version(self):
        document = self.new_document()
        self.assertEqual(document.status, DocumentStatus.DRAFT)
        self.assertRegex(document.reference_no, r"^ESIRA-\d{4}-0001$")
        self.assertEqual(document.page_count, 2)
        version = document.current_version
        self.assertEqual(version.number, 1)
        self.assertEqual(version.kind, DocumentVersion.Kind.ORIGINAL)
        self.assertEqual(len(version.read_verified()), version.size)
        self.assertTrue(
            AuditEntry.objects.filter(document=document, action=AuditAction.UPLOADED).exists()
        )
        # Mirrored into the system-wide audit log.
        self.assertTrue(
            AuditEvent.objects.filter(action=Action.UPLOAD, detail__startswith="e-SIRA").exists()
        )

    def test_reference_numbers_are_sequential(self):
        first, second = self.new_document(), self.new_document()
        self.assertEqual(int(second.reference_no[-4:]), int(first.reference_no[-4:]) + 1)

    def test_a_viewer_cannot_upload(self):
        with self.assertRaises(PermissionDenied):
            self.new_document(owner=self.approver)
        self.client.force_login(self.approver)
        self.assertEqual(self.client.get(reverse("esira:upload")).status_code, 403)

    def test_upload_through_the_form(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("esira:upload"), {
            "title": "Letter to the LGUs", "mode": "upload", "pdf_file": upload(),
        })
        document = EsiraDocument.objects.get(title="Letter to the LGUs")
        self.assertRedirects(response, reverse("esira:workspace", args=[document.pk]))

    def test_a_non_pdf_is_refused(self):
        with self.assertRaises(workflow.WorkflowError):
            workflow.create_document(
                self.owner, title="x",
                pdf_file=SimpleUploadedFile("x.pdf", b"not a pdf at all"),
            )

    def test_versions_and_audit_entries_cannot_be_changed_or_deleted(self):
        document = self.new_document()
        version = document.current_version
        version.note = "rewritten"
        with self.assertRaises(ImmutableRecordError):
            version.save()
        with self.assertRaises(ImmutableRecordError):
            version.delete()
        entry = AuditEntry.objects.filter(document=document).first()
        entry.detail = "rewritten"
        with self.assertRaises(ImmutableRecordError):
            entry.save()
        with self.assertRaises(ImmutableRecordError):
            entry.delete()

    def test_a_tampered_file_is_not_served(self):
        document = self.new_document()
        version = document.current_version
        Path(version.file.path).write_bytes(make_pdf(1))
        self.client.force_login(self.owner)
        response = self.client.get(reverse("esira:file", args=[document.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            AuditEntry.objects.filter(document=document, action=AuditAction.INTEGRITY_FAILURE).exists()
        )

    def test_the_file_is_served_to_the_owner_only(self):
        document = self.new_document()
        self.client.force_login(self.owner)
        response = self.client.get(reverse("esira:file", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        close_response(response)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("esira:file", args=[document.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


class BoxTests(EsiraTestCase):
    def test_owner_places_moves_and_removes_boxes(self):
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [
            self.box(document, self.owner, page=1), self.box(document, self.signer, page=2),
        ])
        self.assertEqual(document.boxes.count(), 2)
        first = document.boxes.get(page=1)
        workflow.save_boxes(document, self.owner, [
            {**self.box(document, self.owner, page=1, x=0.5), "id": first.pk},
        ])
        first.refresh_from_db()
        self.assertAlmostEqual(first.x, 0.5)
        self.assertEqual(document.boxes.count(), 1)
        actions = set(AuditEntry.objects.filter(document=document).values_list("action", flat=True))
        self.assertTrue({AuditAction.BOX_ADDED, AuditAction.BOX_MODIFIED, AuditAction.BOX_REMOVED} <= actions)

    def test_a_box_must_lie_on_a_real_page(self):
        document = self.new_document()
        with self.assertRaises(workflow.WorkflowError):
            workflow.save_boxes(document, self.owner, [self.box(document, self.owner, page=9)])
        with self.assertRaises(workflow.WorkflowError):
            workflow.save_boxes(document, self.owner, [self.box(document, self.owner, x=0.9)])

    def test_only_the_owner_places_boxes_on_a_draft(self):
        document = self.new_document()
        with self.assertRaises(PermissionDenied):
            workflow.save_boxes(document, self.signer, [self.box(document, self.signer)])

    def test_the_boxes_endpoint(self):
        document = self.new_document()
        self.client.force_login(self.owner)
        url = reverse("esira:boxes", args=[document.pk])
        response = self.client.post(
            url, {"boxes": [self.box(document, self.owner)]}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["boxes"]), 1)
        self.assertTrue(response.json()["boxes"][0]["editable"])
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


class CertificateTests(EsiraTestCase):
    def test_registration_stores_the_file_encrypted(self):
        data, cert = PKI.issue("Sam Signer")
        record = workflow.register_certificate(
            self.signer, pkcs12_file=p12_upload(data), passphrase="secret",
        )
        self.assertTrue(record.created)
        self.assertEqual(record.status, SigningCertificate.Status.PENDING)
        self.assertTrue(record.chain_trusted)
        self.assertIn("BEGIN CERTIFICATE", record.certificate_pem)
        self.assertNotIn("PRIVATE KEY", record.certificate_pem)
        record.refresh_from_db()
        self.assertTrue(record.has_stored_credential)
        self.assertEqual(record.pkcs12_filename, "me.p12")
        # Neither the file nor the password is kept in the clear.
        self.assertNotIn(data, bytes(record.pkcs12_sealed))
        self.assertNotIn(b"secret", bytes(record.passphrase_sealed))
        self.assertEqual(unseal(record.pkcs12_sealed), data)
        self.assertEqual(unseal(record.passphrase_sealed), b"secret")

    def test_uploading_the_same_file_again_replaces_the_stored_copy(self):
        data, _ = PKI.issue("Sam Signer")
        first = workflow.register_certificate(self.signer, pkcs12_file=p12_upload(data), passphrase="secret")
        again = workflow.register_certificate(
            self.signer, pkcs12_file=p12_upload(data, name="renamed.pfx"), passphrase="secret",
        )
        self.assertFalse(again.created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(SigningCertificate.objects.filter(user=self.signer).count(), 1)
        self.assertEqual(again.pkcs12_filename, "renamed.pfx")

    @override_settings(ESIRA_CREDENTIAL_KEY="")
    def test_a_changed_key_cannot_open_the_store(self):
        data, _ = PKI.issue("Sam Signer")
        record = workflow.register_certificate(self.signer, pkcs12_file=p12_upload(data), passphrase="secret")
        with override_settings(SECRET_KEY="a-different-secret-key"):
            with self.assertRaisesMessage(workflow.WorkflowError, "could not be decrypted"):
                workflow.reveal_passphrase(self.signer)
        self.assertEqual(workflow.reveal_passphrase(self.signer), "secret")
        self.assertTrue(record.has_stored_credential)

    def test_a_wrong_passphrase_is_refused(self):
        data, _ = PKI.issue("Sam Signer")
        with self.assertRaises(workflow.WorkflowError):
            workflow.register_certificate(self.signer, pkcs12_file=p12_upload(data), passphrase="nope")

    def test_one_certificate_cannot_serve_two_accounts(self):
        data, _ = PKI.issue("Sam Signer")
        workflow.register_certificate(self.signer, pkcs12_file=p12_upload(data), passphrase="secret")
        with self.assertRaisesMessage(workflow.WorkflowError, "another account"):
            workflow.register_certificate(self.outsider, pkcs12_file=p12_upload(data), passphrase="secret")

    def test_an_administrator_cannot_verify_their_own_certificate(self):
        data, _ = PKI.issue("Divina Chief")
        record = workflow.register_certificate(self.admin, pkcs12_file=p12_upload(data), passphrase="secret")
        with self.assertRaises(PermissionDenied):
            workflow.review_certificate(record, self.admin, decision="verify")

    def test_only_verifiers_review(self):
        data, _ = PKI.issue("Sam Signer")
        record = workflow.register_certificate(self.signer, pkcs12_file=p12_upload(data), passphrase="secret")
        with self.assertRaises(PermissionDenied):
            workflow.review_certificate(record, self.owner, decision="verify")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("esira:certificate_review")).status_code, 403)


class StoredCertificateTests(EsiraTestCase):
    def draft_with_box(self):
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        return document

    def test_signs_with_the_stored_password_when_protection_is_off(self):
        self.verified_certificate(self.owner)
        workflow.set_require_passphrase(self.owner, False)
        document = self.draft_with_box()
        signature = workflow.sign(document, self.owner, credentials={"stored": True})
        self.assertTrue(signature.chain_trusted)
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.FULLY_SIGNED)

    def test_protection_on_requires_the_right_password(self):
        self.verified_certificate(self.owner)
        self.assertTrue(SignerProfile.for_user(self.owner).require_passphrase)
        document = self.draft_with_box()
        with self.assertRaisesMessage(workflow.WorkflowError, "Enter your certificate password"):
            workflow.sign(document, self.owner, credentials={"stored": True})
        with self.assertRaisesMessage(workflow.WorkflowError, "passphrase"):
            workflow.sign(document, self.owner, credentials={"stored": True, "passphrase": "wrong"})
        workflow.sign(document, self.owner, credentials={"stored": True, "passphrase": "secret"})

    def test_an_unverified_stored_certificate_cannot_sign(self):
        data, _ = PKI.issue("Olivia Owner")
        workflow.register_certificate(self.owner, pkcs12_file=p12_upload(data), passphrase="secret")
        workflow.set_require_passphrase(self.owner, False)
        with self.assertRaisesMessage(workflow.WorkflowError, "no verified certificate file"):
            workflow.sign(self.draft_with_box(), self.owner, credentials={"stored": True})

    def test_removed_credentials_cannot_sign(self):
        self.verified_certificate(self.owner)
        workflow.set_require_passphrase(self.owner, False)
        workflow.remove_stored_certificate(self.owner, workflow.stored_certificate(self.owner))
        self.assertIsNone(workflow.stored_certificate(self.owner))
        with self.assertRaises(workflow.WorkflowError):
            workflow.sign(self.draft_with_box(), self.owner, credentials={"stored": True})
        self.assertTrue(AuditEntry.objects.filter(action=AuditAction.CERT_REMOVED).exists())

    def test_signature_image_is_drawn_in_the_box(self):
        self.verified_certificate(self.owner)
        workflow.set_require_passphrase(self.owner, False)
        workflow.set_signature_image(self.owner, process_signature_image(signature_png()))
        document = self.draft_with_box()
        workflow.sign(document, self.owner, credentials={"stored": True})
        reports = verify_pdf(document.current_version.read_verified(), document.signatures.all())
        self.assertTrue(all(r.intact and r.valid for r in reports))

    def test_a_non_image_is_refused_as_a_signature(self):
        with self.assertRaises(ValidationError):
            process_signature_image(SimpleUploadedFile("sig.png", b"not a picture"))


def signature_png(width=400, height=160):
    picture = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for x in range(40, width - 40):
        picture.putpixel((x, height // 2 + (x % 30) - 15), (10, 10, 60, 255))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return SimpleUploadedFile("sig.png", buffer.getvalue(), content_type="image/png")


class SignatureStyleTests(EsiraTestCase):
    def setUp(self):
        self.verified_certificate(self.owner)
        workflow.set_require_passphrase(self.owner, False)

    def sign_with(self, style):
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        workflow.sign(document, self.owner, credentials={"stored": True}, style=style)
        reports = verify_pdf(document.current_version.read_verified(), document.signatures.all())
        self.assertTrue(reports and all(r.intact and r.valid for r in reports))
        return document

    def test_the_built_in_styles(self):
        keys = [s["key"] for s in workflow.signature_styles(self.owner)]
        self.assertEqual(keys, ["description"])  # no signature image yet
        workflow.set_signature_image(self.owner, process_signature_image(signature_png()))
        keys = [s["key"] for s in workflow.signature_styles(self.owner)]
        self.assertEqual(keys, ["description", "graphic"])
        self.assertEqual(workflow.default_style_key(self.owner), "graphic")

    def test_every_style_signs(self):
        workflow.set_signature_image(self.owner, process_signature_image(signature_png()))
        row = workflow.add_signature_style(
            self.owner, name="IVY D. BACON", content=process_signature_image(signature_png()),
        )
        for key in ("description", "graphic", row.key):
            self.sign_with(key)
        # The last style signed with is offered first next time.
        self.assertEqual(workflow.default_style_key(self.owner), row.key)

    def test_unavailable_styles_are_refused(self):
        with self.assertRaisesMessage(workflow.WorkflowError, "needs a signature image"):
            self.sign_with("graphic")
        theirs = workflow.add_signature_style(
            self.signer, name="Sam", content=process_signature_image(signature_png()),
        )
        with self.assertRaisesMessage(workflow.WorkflowError, "not available"):
            self.sign_with(theirs.key)

    def test_custom_styles_are_limited_and_deletable(self):
        for n in range(SignatureStyle.MAX_PER_USER):
            workflow.add_signature_style(
                self.owner, name=f"Style {n}", content=process_signature_image(signature_png()),
            )
        with self.assertRaisesMessage(workflow.WorkflowError, "up to"):
            workflow.add_signature_style(
                self.owner, name="One more", content=process_signature_image(signature_png()),
            )
        row = self.owner.esira_signature_styles.first()
        storage, name = row.image.storage, row.image.name
        with self.assertRaises(PermissionDenied):
            workflow.delete_signature_style(self.signer, row)
        workflow.delete_signature_style(self.owner, row)
        self.assertFalse(storage.exists(name))

    def test_page_add_and_delete(self):
        self.client.force_login(self.owner)
        url = reverse("esira:signature_styles")
        page = self.client.get(url)
        self.assertContains(page, "Description Only")
        self.assertContains(page, "Available by Default")

        response = self.client.post(url, {"action": "add", "name": "IVY D. BACON", "image": signature_png()})
        self.assertRedirects(response, url)
        row = self.owner.esira_signature_styles.get()
        self.assertContains(self.client.get(url), "IVY D. BACON")
        image = self.client.get(reverse("esira:signature_style_image", args=[row.pk]))
        self.assertEqual(image["Content-Type"], "image/png")
        close_response(image)

        self.client.force_login(self.signer)
        self.assertEqual(
            self.client.get(reverse("esira:signature_style_image", args=[row.pk])).status_code, 404,
        )
        self.assertEqual(self.client.post(url, {"action": "delete", "style": row.pk}).status_code, 404)

        self.client.force_login(self.owner)
        self.client.post(url, {"action": "delete", "style": row.pk})
        self.assertFalse(self.owner.esira_signature_styles.exists())

    def test_a_bad_upload_reopens_the_dialog(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("esira:signature_styles"), {
            "action": "add", "name": "Broken",
            "image": SimpleUploadedFile("x.png", b"nope", content_type="image/png"),
        })
        self.assertContains(response, "data-open-on-load")
        self.assertContains(response, "not an image")

    def test_sign_dialog_offers_the_styles(self):
        workflow.add_signature_style(
            self.owner, name="IVY D. BACON", content=process_signature_image(signature_png()),
        )
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        self.client.force_login(self.owner)
        page = self.client.get(reverse("esira:workspace", args=[document.pk]))
        self.assertContains(page, 'value="description"')
        self.assertContains(page, "IVY D. BACON")


class CertificatePageTests(EsiraTestCase):
    def test_page_and_actions(self):
        self.client.force_login(self.signer)
        url = reverse("esira:certificates")
        self.assertEqual(self.client.get(url).status_code, 200)

        data, _ = PKI.issue("Sam Signer")
        response = self.client.post(url, {
            "action": "certificate", "cert-passphrase": "secret",
            "cert-certificate_file": p12_upload(data, name="sam.p12"),
        })
        self.assertRedirects(response, url)
        page = self.client.get(url)
        self.assertContains(page, "sam.p12")

        self.client.post(url, {"action": "protection"})  # switch unchecked = off
        self.assertFalse(SignerProfile.for_user(self.signer).require_passphrase)
        self.client.post(url, {"action": "protection", "require_passphrase": "on"})
        self.assertTrue(SignerProfile.for_user(self.signer).require_passphrase)

        reveal = self.client.post(reverse("esira:certificate_password"))
        self.assertEqual(reveal.json(), {"password": "secret"})
        self.assertEqual(reveal["Cache-Control"], "no-store")
        self.assertTrue(AuditEntry.objects.filter(
            action=AuditAction.CERT_PASSWORD_VIEWED, actor=self.signer).exists())
        self.assertEqual(self.client.get(reverse("esira:certificate_password")).status_code, 405)

    def test_a_wrong_password_is_shown_on_the_form(self):
        self.client.force_login(self.signer)
        data, _ = PKI.issue("Sam Signer")
        response = self.client.post(reverse("esira:certificates"), {
            "action": "certificate", "cert-passphrase": "nope",
            "cert-certificate_file": p12_upload(data),
        })
        self.assertContains(response, "could not be opened")
        self.assertFalse(SigningCertificate.objects.filter(user=self.signer).exists())

    def test_nobody_else_sees_or_removes_your_certificate(self):
        self.verified_certificate(self.signer)
        record = workflow.stored_certificate(self.signer)
        self.client.force_login(self.outsider)
        reveal = self.client.post(reverse("esira:certificate_password"))
        self.assertEqual(reveal.status_code, 404)
        response = self.client.post(reverse("esira:certificates"), {
            "action": "remove_certificate", "certificate": record.pk,
        })
        self.assertEqual(response.status_code, 404)
        record.refresh_from_db()
        self.assertTrue(record.has_stored_credential)

    def test_sign_dialog_skips_the_file_when_one_is_stored(self):
        self.verified_certificate(self.owner)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        self.client.force_login(self.owner)
        page = self.client.get(reverse("esira:workspace", args=[document.pk]))
        self.assertContains(page, "Signing with the certificate you keep on file")
        self.assertNotContains(page, 'name="certificate_file"')
        self.assertContains(page, 'name="passphrase"')

        response = self.client.post(reverse("esira:sign", args=[document.pk]), {
            "passphrase": "secret", "confirm": "on",
        })
        self.assertRedirects(response, reverse("esira:detail", args=[document.pk]))
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.FULLY_SIGNED)


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


class SigningTests(EsiraTestCase):
    def test_owner_signs_their_own_draft(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        original_hash = document.current_version.sha256
        workflow.save_boxes(document, self.owner, [
            self.box(document, self.owner, page=1), self.box(document, self.owner, page=2),
        ])
        signature = workflow.sign(document, self.owner, credentials=self.credentials(p12), reason="Approved")

        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.FULLY_SIGNED)
        self.assertEqual(signature.box_count, 2)
        self.assertTrue(signature.chain_trusted)
        self.assertEqual(document.versions.count(), 2)
        self.assertEqual(document.original_version.sha256, original_hash)
        self.assertFalse(document.boxes.filter(signature__isnull=True).exists())

        reports = verify_pdf(document.current_version.read_verified(), document.signatures.all())
        self.assertEqual(len(reports), 2)
        for report in reports:
            self.assertTrue(report.intact and report.valid and report.trusted, report.summary)
            self.assertIsNotNone(report.esira_signature)
        self.assertTrue(AuditEvent.objects.filter(action=Action.SIGN).exists())

    def test_the_certificate_must_be_verified(self):
        data, _ = PKI.issue("Olivia Owner")
        workflow.register_certificate(self.owner, pkcs12_file=p12_upload(data), passphrase="secret")
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        with self.assertRaisesMessage(workflow.WorkflowError, "awaiting verification"):
            workflow.sign(document, self.owner, credentials=self.credentials(data))
        document.refresh_from_db()
        self.assertEqual(document.versions.count(), 1)
        self.assertEqual(document.status, DocumentStatus.DRAFT)
        self.assertFalse(document.steps.exists())  # the self-sign step rolled back
        # The refusal is on the record even though everything else rolled back.
        self.assertTrue(
            AuditEntry.objects.filter(document=document, action=AuditAction.SIGN_FAILED).exists()
        )

    def test_someone_elses_certificate_cannot_sign(self):
        owner_p12 = self.verified_certificate(self.owner)
        self.verified_certificate(self.signer)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.signer)])
        workflow.start_routing(document, self.owner, [
            {"recipient": self.signer, "action": StepAction.SIGN, "purpose": "Sign"},
        ])
        with self.assertRaisesMessage(workflow.WorkflowError, "not registered to your account"):
            workflow.sign(document, self.signer, credentials=self.credentials(owner_p12))

    def test_a_certificate_from_outside_pnpki_is_refused(self):
        rogue = TestPKI("Rogue CA")
        data, _ = rogue.issue("Olivia Owner")
        record = workflow.register_certificate(self.owner, pkcs12_file=p12_upload(data), passphrase="secret")
        self.assertFalse(record.chain_trusted)
        workflow.review_certificate(record, self.admin, decision="verify")
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        with self.assertRaisesMessage(workflow.WorkflowError, "does not chain"):
            workflow.sign(document, self.owner, credentials=self.credentials(data))

    @override_settings(DEBUG=True, ESIRA_PNPKI_TRUST_ROOTS=[], ESIRA_ALLOW_UNTRUSTED_CERTIFICATES=True)
    def test_development_mode_signs_but_says_it_is_not_pnpki(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        signature = workflow.sign(document, self.owner, credentials=self.credentials(p12))
        self.assertFalse(signature.chain_trusted)
        entry = AuditEntry.objects.get(document=document, action=AuditAction.SIGNED)
        self.assertIn("NOT PNPKI-verified", entry.detail)

    @override_settings(DEBUG=False, ESIRA_PNPKI_TRUST_ROOTS=[], ESIRA_ALLOW_UNTRUSTED_CERTIFICATES=True)
    def test_the_development_override_is_ignored_outside_debug(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        with self.assertRaisesMessage(workflow.WorkflowError, "No DICT PNPKI root"):
            workflow.sign(document, self.owner, credentials=self.credentials(p12))

    def test_a_wrong_passphrase_at_signing(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        with self.assertRaisesMessage(workflow.WorkflowError, "passphrase"):
            workflow.sign(document, self.owner, credentials=self.credentials(p12, "wrong"))

    def test_a_tampered_version_is_not_signed(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        Path(document.current_version.file.path).write_bytes(make_pdf(2))
        with self.assertRaisesMessage(workflow.WorkflowError, "no longer matches"):
            workflow.sign(document, self.owner, credentials=self.credentials(p12))
        self.assertTrue(
            AuditEntry.objects.filter(document=document, action=AuditAction.INTEGRITY_FAILURE).exists()
        )

    def test_signing_needs_a_box(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        with self.assertRaises(PermissionDenied):
            workflow.sign(document, self.owner, credentials=self.credentials(p12))

    def test_sign_through_the_view(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        self.client.force_login(self.owner)
        response = self.client.post(reverse("esira:sign", args=[document.pk]), {
            "certificate_file": p12_upload(p12), "passphrase": "secret",
            "reason": "Approved", "confirm": "on",
        })
        self.assertRedirects(response, document.get_absolute_url())
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.FULLY_SIGNED)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class RoutingTests(EsiraTestCase):
    def route(self):
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [
            self.box(document, self.owner, page=1), self.box(document, self.signer, page=2),
        ])
        workflow.start_routing(document, self.owner, [
            {"recipient": self.owner, "action": StepAction.SIGN, "purpose": "Prepared by"},
            {"recipient": self.signer, "action": StepAction.SIGN, "purpose": "Recommending approval"},
            {"recipient": self.approver, "action": StepAction.APPROVE, "purpose": "Approval"},
        ])
        document.refresh_from_db()
        return document

    def test_the_full_route(self):
        owner_p12 = self.verified_certificate(self.owner)
        signer_p12 = self.verified_certificate(self.signer)
        document = self.route()
        self.assertEqual(document.status, DocumentStatus.AWAITING_SIGNATURE)

        workflow.sign(document, self.owner, credentials=self.credentials(owner_p12))
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.PARTIALLY_SIGNED)
        self.assertEqual(document.current_step().recipient, self.signer)

        workflow.sign(document, self.signer, credentials=self.credentials(signer_p12))
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.ROUTED)

        workflow.act(document, self.approver, decision="complete", remarks="Approved.")
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.FULLY_SIGNED)

        workflow.complete(document, self.owner)
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.COMPLETED)
        self.assertEqual(document.versions.count(), 3)

        # Both signatures - the owner's from v2 and the signer's added in v3 -
        # validate in the final file.
        reports = verify_pdf(document.current_version.read_verified(), document.signatures.all())
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(r.intact and r.valid and r.trusted for r in reports))

        steps = list(document.steps.order_by("sequence"))
        self.assertEqual([s.status for s in steps],
                         [StepStatus.SIGNED, StepStatus.SIGNED, StepStatus.APPROVED])
        for step in steps:
            self.assertIsNotNone(step.routed_at)
            self.assertIsNotNone(step.received_at)
            self.assertIsNotNone(step.acted_at)

        # Nothing further may be done to a completed document.
        with self.assertRaises(PermissionDenied):
            workflow.save_boxes(document, self.owner, [])
        with self.assertRaises(PermissionDenied):
            workflow.cancel(document, self.owner, "late")

        signer_figures = stats.compute(self.signer)
        self.assertEqual(signer_figures["total_signed"], 1)
        self.assertEqual(signer_figures["signed_week"], 1)
        approver_figures = stats.compute(self.approver)
        self.assertEqual(approver_figures["total_routed_completed"], 1)
        self.assertEqual(approver_figures["total_signed_routed"], 1)
        self.assertEqual(stats.compute(self.owner)["completed"], 1)

    def test_every_box_needs_a_signature_step(self):
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.signer)])
        with self.assertRaisesMessage(workflow.WorkflowError, "no signature step"):
            workflow.start_routing(document, self.owner, [
                {"recipient": self.approver, "action": StepAction.APPROVE},
            ])

    def test_recipients_see_the_document_only_once_it_reaches_them(self):
        document = self.route()
        self.client.force_login(self.approver)
        self.assertEqual(self.client.get(document.get_absolute_url()).status_code, 403)
        self.client.force_login(self.signer)
        self.assertEqual(self.client.get(document.get_absolute_url()).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(document.get_absolute_url()).status_code, 200)

    def test_opening_the_document_records_receipt(self):
        document = self.new_document()
        workflow.start_routing(document, self.owner, [
            {"recipient": self.approver, "action": StepAction.APPROVE, "purpose": "Approval"},
        ])
        self.client.force_login(self.approver)
        self.assertEqual(self.client.get(document.get_absolute_url()).status_code, 200)
        step = document.steps.get()
        self.assertEqual(step.status, StepStatus.RECEIVED)
        self.assertIsNotNone(step.received_at)
        self.assertTrue(AuditEntry.objects.filter(document=document, action=AuditAction.RECEIVED).exists())
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.ROUTED)

    def test_only_the_current_recipient_acts(self):
        document = self.route()
        with self.assertRaises(PermissionDenied):
            workflow.act(document, self.approver, decision="complete")
        with self.assertRaisesMessage(workflow.WorkflowError, "signing workspace"):
            workflow.act(document, self.owner, decision="complete")

    def test_rejection_stops_the_route(self):
        document = self.new_document()
        workflow.start_routing(document, self.owner, [
            {"recipient": self.approver, "action": StepAction.APPROVE},
            {"recipient": self.signer, "action": StepAction.ACKNOWLEDGE},
        ])
        with self.assertRaises(workflow.WorkflowError):
            workflow.act(document, self.approver, decision="reject", remarks="  ")
        workflow.act(document, self.approver, decision="reject", remarks="Wrong addressee.")
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.REJECTED)
        self.assertEqual(document.closed_reason, "Wrong addressee.")
        self.assertEqual(
            list(document.steps.order_by("sequence").values_list("status", flat=True)),
            [StepStatus.REJECTED, StepStatus.CANCELLED],
        )

    def test_forwarding_inserts_a_step(self):
        document = self.new_document()
        workflow.start_routing(document, self.owner, [
            {"recipient": self.approver, "action": StepAction.REVIEW},
            {"recipient": self.signer, "action": StepAction.ACKNOWLEDGE},
        ])
        workflow.act(document, self.approver, decision="complete",
                     forward_to=self.admin, forward_action=StepAction.APPROVE,
                     forward_purpose="For the Chief")
        steps = list(document.steps.order_by("sequence"))
        self.assertEqual([s.recipient for s in steps], [self.approver, self.admin, self.signer])
        self.assertEqual(steps[1].status, StepStatus.PENDING)
        self.assertEqual(steps[1].sender, self.approver)

    def test_routing_without_signatures_completes_the_route(self):
        document = self.new_document()
        workflow.start_routing(document, self.owner, [
            {"recipient": self.approver, "action": StepAction.ACKNOWLEDGE},
        ])
        workflow.act(document, self.approver, decision="complete")
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.ROUTING_COMPLETED)

    def test_cancelling(self):
        document = self.route()
        with self.assertRaises(PermissionDenied):
            workflow.cancel(document, self.outsider, "no")
        workflow.cancel(document, self.owner, "Superseded by a new memo.")
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.CANCELLED)
        self.assertFalse(document.steps.exclude(status=StepStatus.CANCELLED).exists())

    def test_the_route_notifies_the_recipient(self):
        from notifications.models import Notification

        document = self.new_document()
        workflow.start_routing(document, self.owner, [
            {"recipient": self.approver, "action": StepAction.APPROVE},
        ])
        self.assertTrue(Notification.objects.filter(recipient=self.approver, dismissed_at__isnull=True).exists())
        workflow.act(document, self.approver, decision="complete")
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.approver, dismissed_at__isnull=True,
                dedupe_key__startswith="esira:step:",
            ).exists()
        )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


class PageTests(EsiraTestCase):
    def test_the_sidebar_offers_esira_at_the_foot(self):
        self.client.force_login(self.approver)
        response = self.client.get(reverse("core:dashboard"))
        sections = response.context["sidebar_sections"]
        self.assertEqual(sections[-1]["label"], "LGMED Innovation Action")
        self.assertTrue(sections[-1]["pinned"])
        self.assertContains(response, reverse("esira:dashboard"))

    def test_dashboard_and_figures(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("esira:dashboard"))
        self.assertEqual(response.status_code, 200)
        for label in ("Awaiting My Signature", "Out for Signature", "Completed",
                      "Total Documents Signed", "Total Routed Documents Completed",
                      "Total Signed + Routed", "Signed This Week",
                      "Routed Documents Completed This Week", "Total This Week (Signed + Routed)"):
            self.assertContains(response, label)
        data = self.client.get(reverse("esira:stats")).json()
        self.assertEqual(data["scope"], "mine")
        self.assertIn("total_week", data["figures"])

    def test_only_overseers_get_the_office_scope(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("esira:stats") + "?scope=office").json()["scope"], "mine")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("esira:stats") + "?scope=office").json()["scope"], "office")

    def test_pages_render(self):
        p12 = self.verified_certificate(self.owner)
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.owner)])
        workflow.sign(document, self.owner, credentials=self.credentials(p12))
        self.client.force_login(self.owner)
        for name, args in (
            ("esira:list", []), ("esira:upload", []), ("esira:certificates", []),
            ("esira:detail", [document.pk]), ("esira:workspace", [document.pk]),
            ("esira:verify", [document.pk]),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        for view in ("awaiting_me", "out", "signed_by_me", "handled_by_me", "mine"):
            with self.subTest(view=view):
                response = self.client.get(reverse("esira:list") + f"?view={view}&period=week")
                self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("esira:list") + "?view=signed_by_me")
        self.assertContains(response, document.reference_no)
        response = self.client.get(reverse("esira:verify", args=[document.pk]))
        self.assertContains(response, "Valid PNPKI signature")

    def test_the_audit_trail_is_for_overseers(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("esira:audit")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("esira:audit")).status_code, 200)

    def test_route_view(self):
        document = self.new_document()
        workflow.save_boxes(document, self.owner, [self.box(document, self.signer)])
        self.client.force_login(self.owner)
        url = reverse("esira:route", args=[document.pk])
        self.assertContains(self.client.get(url), "Send on route")
        response = self.client.post(url, {
            "steps-TOTAL_FORMS": "1", "steps-INITIAL_FORMS": "0",
            "steps-MIN_NUM_FORMS": "1", "steps-MAX_NUM_FORMS": "30",
            "steps-0-recipient": self.signer.pk, "steps-0-action": StepAction.SIGN,
            "steps-0-purpose": "For signature",
        })
        self.assertRedirects(response, document.get_absolute_url())
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.OUT_FOR_SIGNATURE)
