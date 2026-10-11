"""
Security regression tests.

Each class pins one control from docs/security/SECURITY_FIXES.md, so that a
later change which quietly undoes it fails here rather than in production.
They test behaviour through the same doors an attacker would use - the URL,
the form post, the header - rather than the helper functions alone.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from accounts.models import Role, User, UserModuleAccess
from core.testing import close_response

BASE_DIR = Path(settings.BASE_DIR)
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="lgmed-imms-security-media-")

NO_RECAPTCHA = override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")


def make_user(username, role, **extra):
    return User.objects.create_user(
        username=username, password="Correct-Horse-Battery-9", role=role, **extra
    )


# ---------------------------------------------------------------------------
# Every URL refuses an anonymous visitor unless it is meant to be public
# ---------------------------------------------------------------------------

# URL names an anonymous visitor may open. Everything else must redirect to the
# sign-in page, or answer 403/404/405 - never 200.
PUBLIC_URL_NAMES = {
    "core:home", "core:public_about", "core:public_programs",
    "core:public_outcome", "core:public_program", "core:public_project",
    "core:public_subproject", "core:public_activity", "core:public_document_file",
    "core:public_services", "core:public_announcements", "core:public_announcement",
    "core:public_updates", "core:public_update_week", "core:public_statistics",
    "core:public_reports", "core:public_documents", "core:public_calendar",
    "core:public_contact",
    "pwa_manifest", "pwa_service_worker", "pwa_offline", "pwa_launch",
    "accounts:login",
}

_DUMMY = {"int": "999999", "slug": "no-such-slug", "str": "no-such-thing",
          "path": "no/such/file.pdf", "uuid": "00000000-0000-0000-0000-000000000000"}


def _walk(patterns, prefix="", namespace=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            ns = entry.namespace or ""
            yield from _walk(
                entry.url_patterns,
                prefix + str(entry.pattern),
                f"{namespace}:{ns}".strip(":") if ns else namespace,
            )
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), (
                f"{namespace}:{entry.name}".strip(":") if entry.name else ""
            ), entry


def _concrete(route):
    """A path for a route pattern, with every converter filled in."""
    if route.startswith("^") or "(?P" in route:
        return None                    # regex routes (the Django admin's own)
    url = re.sub(
        r"<(?:(\w+):)?(\w+)>",
        lambda m: _DUMMY.get(m.group(1) or "str", "x"),
        route,
    )
    return "/" + url


class AnonymousAccessTests(TestCase):
    def test_no_internal_url_answers_an_anonymous_visitor(self):
        client = Client()
        leaked = []
        checked = 0
        for route, name, _pattern in _walk(get_resolver().url_patterns):
            if name in PUBLIC_URL_NAMES or route.startswith("django-admin"):
                continue
            url = _concrete(route)
            if url is None:
                continue
            for method in ("get", "post"):
                response = getattr(client, method)(url)
                checked += 1
                if response.status_code == 200:
                    leaked.append(f"{method.upper()} {url} ({name})")
                elif response.status_code in (301, 302):
                    location = response["Location"]
                    if "/accounts/login" not in location and "/django-admin" not in location:
                        # A redirect elsewhere is fine only if it is not
                        # content - e.g. /staff -> login. Note it to be sure.
                        target = client.get(location)
                        if target.status_code == 200 and "/accounts/login" not in location:
                            leaked.append(f"{method.upper()} {url} -> {location}")
                close_response(response)
        self.assertGreater(checked, 100)
        self.assertEqual(leaked, [], "Reachable without signing in:\n" + "\n".join(leaked))

    def test_django_admin_requires_sign_in(self):
        response = self.client.get("/django-admin/")
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# /media/ is a gateway, not a directory listing
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MediaGatewayTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        from documents.models import DocumentType

        cls.staff = make_user("media.staff", Role.LGMED_STAFF)
        cls.viewer = make_user("media.viewer", Role.VIEWER)
        cls.document_type = DocumentType.objects.create(name="Memorandum")

    def _incoming(self, content=b"%PDF-1.4 confidential"):
        from incoming.models import IncomingDocument

        document = IncomingDocument.objects.create(
            docket_number="SEC-0001", subject="Confidential request",
            document_type=self.document_type, date_received=timezone.localdate(),
            source_office="Office", created_by=self.staff,
        )
        document.attachment.save("letter.pdf", ContentFile(content))
        return document

    def get(self, url, client=None):
        response = (client or self.client).get(url)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        close_response(response)
        return response, body

    def test_internal_attachment_is_refused_to_anonymous_visitors(self):
        document = self._incoming()
        response, body = self.get(document.attachment.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"confidential", body)

    def test_internal_attachment_is_served_to_staff(self):
        document = self._incoming()
        self.client.force_login(self.viewer)
        response, body = self.get(document.attachment.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, b"%PDF-1.4 confidential")
        self.assertIn("private", response["Cache-Control"])

    def test_a_closed_module_closes_its_files_too(self):
        document = self._incoming()
        UserModuleAccess.objects.create(user=self.viewer, module="incoming", allowed=False)
        self.client.force_login(self.viewer)
        response, _ = self.get(document.attachment.url)
        self.assertEqual(response.status_code, 404)

    def test_published_announcement_photo_is_public_and_draft_is_not(self):
        from announcements.models import Announcement

        live = Announcement.objects.create(
            title="Live", summary="s", is_published=True, published_on=timezone.localdate(),
        )
        live.image.save("live.png", ContentFile(b"\x89PNG\r\n\x1a\n...."))
        draft = Announcement.objects.create(
            title="Draft", summary="s", is_published=False, published_on=timezone.localdate(),
        )
        draft.image.save("draft.png", ContentFile(b"\x89PNG\r\n\x1a\n...."))

        self.assertEqual(self.get(live.image.url)[0].status_code, 200)
        self.assertEqual(self.get(draft.image.url)[0].status_code, 404)

    def test_unpublished_report_file_is_not_public(self):
        from reports.models import Report, ReportStatus

        report = Report.objects.create(title="Q1", year=2026, status=ReportStatus.DRAFT)
        report.file.save("q1.pdf", ContentFile(b"%PDF-1.4 draft"))
        self.assertEqual(self.get(report.file.url)[0].status_code, 404)
        report.status = ReportStatus.PUBLISHED
        report.save()
        self.assertEqual(self.get(report.file.url)[0].status_code, 200)

    def test_files_no_record_claims_are_not_served(self):
        os.makedirs(os.path.join(TEST_MEDIA_ROOT, "stray"), exist_ok=True)
        with open(os.path.join(TEST_MEDIA_ROOT, "stray", "secret.pdf"), "wb") as handle:
            handle.write(b"%PDF-1.4 stray")
        self.client.force_login(self.staff)
        self.assertEqual(self.get("/media/stray/secret.pdf")[0].status_code, 404)

    def test_path_traversal_is_refused(self):
        self.client.force_login(self.staff)
        for path in ("/media/../config/settings.py", "/media/%2e%2e/manage.py",
                     "/media/incoming/..%2f..%2fmanage.py", "/media/..\\manage.py"):
            self.assertEqual(self.get(path)[0].status_code, 404, path)

    def test_markup_is_never_served_inline(self):
        document = self._incoming()
        document.attachment.save("page.html", ContentFile(b"<script>alert(1)</script>"))
        self.client.force_login(self.staff)
        response, _ = self.get(document.attachment.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertEqual(response["Content-Type"], "application/octet-stream")

    def test_every_file_field_in_public_media_is_covered(self):
        """A new FileField in MEDIA_ROOT must be added to core.media.SOURCES."""
        from django.apps import apps
        from django.core.files.storage import default_storage
        from django.db.models import FileField

        from core.media import SOURCES

        covered = {(s.model.lower(), s.field) for s in SOURCES}
        missing = []
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if isinstance(field, FileField) and field.storage is default_storage:
                    key = (model._meta.label_lower, field.name)
                    if key not in covered:
                        missing.append(".".join(key))
        self.assertEqual(missing, [])


# ---------------------------------------------------------------------------
# Sign-in throttle
# ---------------------------------------------------------------------------


@NO_RECAPTCHA
@override_settings(LOGIN_THROTTLE_PER_USER_IP=3, LOGIN_THROTTLE_PER_USER=6,
                   LOGIN_THROTTLE_PER_IP=10, LOGIN_THROTTLE_WINDOW=600)
class LoginThrottleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("throttle.me", Role.VIEWER)

    def setUp(self):
        cache.clear()

    def attempt(self, password, username="throttle.me", ip="10.0.0.1"):
        return self.client.post(
            reverse("accounts:login"),
            {"username": username, "password": password},
            REMOTE_ADDR=ip,
        )

    def test_correct_password_is_refused_once_throttled(self):
        for _ in range(3):
            self.assertEqual(self.attempt("wrong").status_code, 200)
        response = self.attempt("Correct-Horse-Battery-9")
        self.assertEqual(response.status_code, 200)        # form re-shown, not signed in
        self.assertContains(response, "Too many unsuccessful sign-in attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_before_the_limit_clears_the_count(self):
        self.attempt("wrong")
        self.attempt("wrong")
        self.assertEqual(self.attempt("Correct-Horse-Battery-9").status_code, 302)
        self.client.logout()
        for _ in range(2):
            self.attempt("wrong")
        self.assertEqual(self.attempt("Correct-Horse-Battery-9").status_code, 302)

    def test_another_machine_is_not_locked_out_by_a_few_failures(self):
        for _ in range(3):
            self.attempt("wrong", ip="10.0.0.66")
        self.assertEqual(self.attempt("Correct-Horse-Battery-9", ip="10.0.0.2").status_code, 302)

    def test_spraying_many_accounts_from_one_address_is_throttled(self):
        for n in range(10):
            self.attempt("wrong", username=f"nobody{n}", ip="10.0.0.9")
        response = self.attempt("Correct-Horse-Battery-9", ip="10.0.0.9")
        self.assertContains(response, "Too many unsuccessful sign-in attempts")

    def test_forged_forwarded_for_does_not_reset_the_count(self):
        for n in range(3):
            self.client.post(
                reverse("accounts:login"),
                {"username": "throttle.me", "password": "wrong"},
                REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR=f"1.2.3.{n}",
            )
        self.assertContains(self.attempt("Correct-Horse-Battery-9"), "Too many")


class ClientAddressTests(SimpleTestCase):
    def test_forwarded_for_is_ignored_unless_a_proxy_is_trusted(self):
        from audit.recording import client_ip

        request = RequestFactory().get("/", REMOTE_ADDR="10.1.1.1",
                                       HTTP_X_FORWARDED_FOR="6.6.6.6, 10.9.9.9")
        with override_settings(TRUST_X_FORWARDED_FOR=False):
            self.assertEqual(client_ip(request), "10.1.1.1")
        with override_settings(TRUST_X_FORWARDED_FOR=True):
            # The last hop - the one the trusted proxy appended - not the first.
            self.assertEqual(client_ip(request), "10.9.9.9")

    def test_garbage_addresses_are_dropped(self):
        from audit.recording import client_ip

        request = RequestFactory().get("/", REMOTE_ADDR="not-an-ip")
        self.assertIsNone(client_ip(request))


# ---------------------------------------------------------------------------
# Privilege escalation: Administrator -> System Administrator
# ---------------------------------------------------------------------------


@NO_RECAPTCHA
class RoleEscalationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superadmin = make_user("esc.super", Role.SUPERADMIN, email="s@example.com")
        cls.admin = make_user("esc.admin", Role.ADMIN, email="a@example.com")
        cls.staff = make_user("esc.staff", Role.LGMED_STAFF, email="t@example.com")

    def user_post(self, user=None, **changes):
        user = user or self.staff
        data = {
            "username": user.username, "first_name": "F", "last_name": "L",
            "email": user.email, "position": "", "office": "", "contact_number": "",
            "code_initials": "", "role": user.role, "is_active": "on",
        }
        data.update(changes)
        return data

    def test_administrator_cannot_promote_anyone_to_system_administrator(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_update", args=[self.staff.pk]),
            self.user_post(role=Role.SUPERADMIN),
        )
        self.assertEqual(response.status_code, 200)       # form error, not saved
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, Role.LGMED_STAFF)

    def test_administrator_cannot_create_a_system_administrator(self):
        self.client.force_login(self.admin)
        data = self.user_post(username="new.super", email="n@example.com", role=Role.SUPERADMIN)
        self.client.post(reverse("accounts:user_create"), data)
        self.assertFalse(User.objects.filter(username="new.super").exists())

    def test_administrator_cannot_take_over_a_system_administrator_account(self):
        self.client.force_login(self.admin)
        pk = self.superadmin.pk
        for name, method, data in (
            ("accounts:user_update", "get", None),
            ("accounts:user_update", "post", self.user_post(self.superadmin, email="evil@example.com")),
            ("accounts:user_password", "get", None),
            ("accounts:user_password", "post", {"new_password1": "Takeover-Pass-12345",
                                                "new_password2": "Takeover-Pass-12345"}),
            ("accounts:user_mfa_reset", "post", {}),
            ("accounts:user_activation", "post", {}),
        ):
            response = getattr(self.client, method)(reverse(name, args=[pk]), data)
            self.assertEqual(response.status_code, 403, f"{method} {name}")
        self.superadmin.refresh_from_db()
        self.assertTrue(self.superadmin.check_password("Correct-Horse-Battery-9"))
        self.assertTrue(self.superadmin.is_active)
        self.assertEqual(self.superadmin.email, "s@example.com")

    def test_system_administrator_may_still_grant_the_role(self):
        self.client.force_login(self.superadmin)
        response = self.client.post(
            reverse("accounts:user_update", args=[self.staff.pk]),
            self.user_post(role=Role.SUPERADMIN),
        )
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, Role.SUPERADMIN)

    def test_administrator_still_manages_ordinary_accounts(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("accounts:user_activation", args=[self.staff.pk]))
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# An encoder cannot approve or publish through the record forms
# ---------------------------------------------------------------------------


class PublicationByEncoderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.encoder = make_user("pub.encoder", Role.ENCODER)
        cls.approver = make_user("pub.approver", Role.LGMED_STAFF)

    def report_data(self, status):
        return {"title": "Quarterly", "reference_number": "", "period": "QUARTERLY",
                "year": "2026", "program": "", "summary": "", "prepared_by": "",
                "status": status, "review_remarks": ""}

    def test_encoder_cannot_publish_a_report(self):
        from reports.models import Report

        self.client.force_login(self.encoder)
        self.client.post(reverse("reports:create"), self.report_data("PUBLISHED"))
        self.assertFalse(Report.objects.filter(status="PUBLISHED").exists())

    def test_approver_can_publish_a_report(self):
        from reports.models import Report

        self.client.force_login(self.approver)
        self.client.post(reverse("reports:create"), self.report_data("PUBLISHED"))
        self.assertTrue(Report.objects.filter(status="PUBLISHED").exists())

    def test_encoder_edit_keeps_an_approved_status(self):
        from reports.models import Report, ReportStatus

        report = Report.objects.create(title="Q", year=2026, status=ReportStatus.PUBLISHED)
        self.client.force_login(self.encoder)
        self.client.post(reverse("reports:update", args=[report.pk]),
                         self.report_data("DRAFT") | {"title": "Q edited"})
        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.PUBLISHED)
        self.assertEqual(report.title, "Q edited")

    def test_encoder_cannot_put_an_announcement_on_the_public_site(self):
        from announcements.models import Announcement

        self.client.force_login(self.encoder)
        self.client.post(reverse("announcements:create"), {
            "title": "Encoder news", "category": "NEWS",
            "published_on": timezone.localdate().isoformat(),
            "summary": "s", "body": "", "image_alt": "",
            "is_published": "on", "is_featured": "on",
        })
        item = Announcement.objects.filter(title="Encoder news").first()
        if item is not None:
            self.assertFalse(item.is_published)
            self.assertFalse(item.is_featured)


# ---------------------------------------------------------------------------
# CSRF, headers, cookies
# ---------------------------------------------------------------------------


@NO_RECAPTCHA
class RequestForgeryAndHeaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("hdr.user", Role.VIEWER)

    def test_login_post_without_csrf_token_is_refused(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("accounts:login"),
                               {"username": "hdr.user", "password": "Correct-Horse-Battery-9"})
        self.assertEqual(response.status_code, 403)

    def test_state_change_without_csrf_token_is_refused(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse("notifications:read_all"))
        self.assertEqual(response.status_code, 403)

    def test_security_headers_on_a_page(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["Cross-Origin-Opener-Policy"], "same-origin")
        policy = response.get("Content-Security-Policy") or response.get(
            "Content-Security-Policy-Report-Only")
        self.assertIn("frame-ancestors 'self'", policy)
        self.assertIn("object-src 'none'", policy)
        script_src = re.search(r"script-src ([^;]+)", policy).group(1)
        self.assertNotIn("'unsafe-inline'", script_src)
        self.assertNotIn("'unsafe-eval'", script_src)

    def test_inline_scripts_carry_the_request_nonce(self):
        response = self.client.get(reverse("core:home"))
        nonce = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"]).group(1)
        for tag in re.findall(rb"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>", response.content):
            self.assertIn(f'nonce="{nonce}"'.encode(), tag)

    def test_cookie_flags(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        response = self.client.post(reverse("accounts:login"),
                                    {"username": "hdr.user", "password": "Correct-Horse-Battery-9"})
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

    def test_session_key_rotates_at_sign_in(self):
        self.client.get(reverse("accounts:login"))
        self.client.session.save()
        before = self.client.session.session_key
        self.client.post(reverse("accounts:login"),
                         {"username": "hdr.user", "password": "Correct-Horse-Battery-9"})
        self.assertNotEqual(self.client.session.session_key, before)

    def test_password_change_ends_other_sessions(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)
        self.user.set_password("A-New-Long-Password-77")
        self.user.save()
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)


class TemplateHygieneTests(SimpleTestCase):
    """Static checks that keep the Content-Security-Policy workable."""

    def templates(self):
        return list((BASE_DIR / "templates").rglob("*.html"))

    def test_no_inline_event_handlers(self):
        offenders = []
        for path in self.templates():
            text = path.read_text(encoding="utf-8")
            if re.search(r"\son[a-z]+\s*=\s*[\"']", text):
                offenders.append(str(path.relative_to(BASE_DIR)))
        self.assertEqual(offenders, [])

    def test_inline_scripts_have_a_nonce(self):
        offenders = []
        for path in self.templates():
            for tag in re.findall(r"<script\b[^>]*>", path.read_text(encoding="utf-8")):
                if "src=" in tag or "application/json" in tag:
                    continue
                if 'nonce="{{ csp_nonce }}"' not in tag:
                    offenders.append(f"{path.relative_to(BASE_DIR)}: {tag}")
        self.assertEqual(offenders, [])


# ---------------------------------------------------------------------------
# Output encoding
# ---------------------------------------------------------------------------


class OutputEncodingTests(SimpleTestCase):
    def test_script_json_cannot_close_its_script_element(self):
        import json

        from core.safe_json import script_json

        payload = {"label": "</script><script>alert(1)</script>&"}
        encoded = script_json(payload)
        self.assertNotIn("<", encoded)
        self.assertNotIn(">", encoded)
        self.assertEqual(json.loads(encoded), payload)

    def test_csv_cells_cannot_become_formulas(self):
        from core.csv_safe import neutralise

        self.assertEqual(neutralise('=HYPERLINK("http://x")'), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(neutralise("+cmd"), "'+cmd")
        self.assertEqual(neutralise("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(neutralise("-12.5"), "-12.5")
        self.assertEqual(neutralise("Plain text"), "Plain text")
        self.assertEqual(neutralise(42), 42)

    def test_open_redirects_are_refused(self):
        from core.redirects import safe_next

        request = RequestFactory().get("/", HTTP_HOST="testserver")
        for bad in ("https://evil.example/", "//evil.example", "/\\evil.example",
                    "javascript:alert(1)"):
            self.assertEqual(safe_next(request, bad, "/fallback/"), "/fallback/", bad)
        self.assertEqual(safe_next(request, "/app/programs/", "/fallback/"), "/app/programs/")


class RefererRedirectTests(TestCase):
    def test_notification_redirect_ignores_a_foreign_referer(self):
        user = make_user("ref.user", Role.VIEWER)
        self.client.force_login(user)
        response = self.client.post(reverse("notifications:read_all"),
                                    HTTP_REFERER="https://evil.example/phish")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example", response["Location"])


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


class UploadValidationTests(SimpleTestCase):
    def check(self, name, content):
        from documents.forms import validate_upload

        return validate_upload(SimpleUploadedFile(name, content))

    def test_web_page_renamed_to_pdf_is_refused(self):
        from django import forms

        with self.assertRaises(forms.ValidationError):
            self.check("minutes.pdf", b"<html><script>alert(1)</script></html>")

    def test_executable_extension_is_refused(self):
        from django import forms

        for name in ("tool.exe", "page.html", "image.svg", "script.js"):
            with self.assertRaises(forms.ValidationError, msg=name):
                self.check(name, b"MZ....")

    def test_genuine_files_pass(self):
        self.check("report.pdf", b"%PDF-1.7\n...")
        self.check("photo.png", b"\x89PNG\r\n\x1a\n....")
        self.check("sheet.xlsx", b"PK\x03\x04....")
        self.check("data.csv", b"name,count\nA,1\n")

    def test_incoming_form_validates_its_attachment(self):
        from incoming.forms import IncomingUpdateForm

        form = IncomingUpdateForm(
            data={"action_taken": "Done", "remarks": "", "status": "IN_PROGRESS"},
            files={"attachment": SimpleUploadedFile("x.html", b"<script>")},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)


# ---------------------------------------------------------------------------
# Error handling and fail-closed configuration
# ---------------------------------------------------------------------------


class SafeErrorTests(SimpleTestCase):
    def test_server_error_page_survives_a_broken_render(self):
        from unittest import mock

        from core import errors

        request = RequestFactory().get("/")
        with mock.patch.object(errors, "_branded_server_error", side_effect=RuntimeError("db down")):
            response = errors.server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"db down", response.content)
        self.assertNotIn(b"Traceback", response.content)


class FailClosedSettingsTests(SimpleTestCase):
    """A production server without its secrets must refuse to start."""

    def import_settings(self, **env):
        environment = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **env}
        # Settings read <venv>/lgmed.env with setdefault, so an explicit empty
        # value here wins over the developer's file.
        return subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            cwd=BASE_DIR, env=environment, capture_output=True, text=True, timeout=120,
        )

    def test_missing_secret_key_refuses_to_start(self):
        result = self.import_settings(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="",
                                      DJANGO_ALLOWED_HOSTS="example.org", MYSQL_PASSWORD="x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY is not set", result.stderr)

    def test_weak_secret_key_refuses_to_start(self):
        result = self.import_settings(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="short",
                                      DJANGO_ALLOWED_HOSTS="example.org", MYSQL_PASSWORD="x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("too weak", result.stderr)

    def test_missing_allowed_hosts_refuses_to_start(self):
        result = self.import_settings(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="k" * 30 + "abcdefghijklmnopqrstu",
                                      DJANGO_ALLOWED_HOSTS="", MYSQL_PASSWORD="x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_ALLOWED_HOSTS", result.stderr)

    def test_debug_is_off_unless_asked_for(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings';"
             "import django; django.setup(); from django.conf import settings;"
             "print('DEBUG', settings.DEBUG)"],
            cwd=BASE_DIR,
            env={**os.environ, "DJANGO_DEBUG": "", "DJANGO_SECRET_KEY": "k" * 30 + "abcdefghijklmnopqrstu",
                 "DJANGO_ALLOWED_HOSTS": "example.org", "MYSQL_PASSWORD": "x"},
            capture_output=True, text=True, timeout=120,
        )
        self.assertIn("DEBUG False", result.stdout, result.stderr)


class MalformedQueryTests(TestCase):
    def test_malformed_list_filters_do_not_cause_server_errors(self):
        self.client.force_login(make_user("query.user", Role.VIEWER))
        for url in (
            reverse("incoming:list") + "?document_type=abc&from=not-a-date&to=%00",
            reverse("monitoring:list") + "?monitoring_date__year=abc&sort=password",
            reverse("documents:list") + "?document_type=1%27%20OR%201=1--",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
