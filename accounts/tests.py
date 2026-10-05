"""Tests for account administration and the role matrix."""

import io
import re
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from PIL import Image

from accounts import photos, recaptcha
from accounts.capabilities import CAPABILITIES, role_matrix
from accounts.models import Role, User
from audit.models import Action, AuditEvent


class UserAdministrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", first_name="Antonio",
            last_name="Villanueva", role=Role.ADMIN,
        )
        cls.other_admin = User.objects.create_user(
            username="admin2", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", first_name="Karl Kevin",
            last_name="Bacon", role=Role.LGMED_STAFF,
        )

    # -- access ---------------------------------------------------------

    def test_non_administrators_are_refused(self):
        self.client.force_login(self.staff)
        for name, args in [
            ("accounts:user_list", []),
            ("accounts:user_create", []),
            ("accounts:role_list", []),
            ("accounts:user_detail", [self.admin.pk]),
            ("accounts:user_update", [self.admin.pk]),
            ("accounts:user_password", [self.admin.pk]),
        ]:
            with self.subTest(route=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 403)

    def test_a_non_administrator_cannot_create_an_account_by_posting(self):
        self.client.force_login(self.staff)
        before = User.objects.count()
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "username": "sneaked.in", "first_name": "S", "last_name": "I",
                "role": Role.ADMIN, "is_active": "on",
                "password1": "Str0ng-Passw0rd!", "password2": "Str0ng-Passw0rd!",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.count(), before)

    # -- creating -------------------------------------------------------

    def _create(self, **overrides):
        data = {
            "username": "new.officer",
            "first_name": "Maria", "last_name": "Reyes",
            "email": "maria.reyes@caraga.dilg.gov.ph",
            "position": "Project Evaluation Officer",
            "office": "LGMED", "contact_number": "",
            "role": Role.ENCODER, "is_active": "on",
        }
        data.update(overrides)
        self.client.force_login(self.admin)
        return self.client.post(reverse("accounts:user_create"), data)

    @override_settings(ACCOUNT_NOTIFY_EMAILS=[])
    def test_administrator_creates_an_account_and_it_is_emailed_its_details(self):
        from django.core import mail

        response = self._create()
        self.assertEqual(response.status_code, 302)

        created = User.objects.get(username="new.officer")
        self.assertEqual(created.role, Role.ENCODER)
        self.assertTrue(
            AuditEvent.objects.filter(
                action=Action.CREATE, target_label="Maria Reyes"
            ).exists()
        )

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["maria.reyes@caraga.dilg.gov.ph"])
        self.assertIn("Welcome", sent.subject)
        for body in (sent.body, sent.alternatives[0][0]):
            self.assertIn("Maria Reyes", body)
            self.assertIn(Role.ENCODER.label, body)
            self.assertIn("new.officer", body)
            self.assertIn("/accounts/login/", body)

        # The emailed password is the one that actually signs in.
        password = re.search(r"Temporary password:\s+(\S+)", sent.body).group(1)
        self.assertTrue(created.check_password(password))

    @override_settings(ACCOUNT_NOTIFY_EMAILS=["records@example.com"])
    def test_the_notify_address_is_told_without_the_password(self):
        from django.core import mail

        self._create()
        self.assertEqual(len(mail.outbox), 2)
        welcome, notice = mail.outbox
        self.assertEqual(welcome.to, ["maria.reyes@caraga.dilg.gov.ph"])
        self.assertEqual(notice.to, ["records@example.com"])

        password = re.search(r"Temporary password:\s+(\S+)", welcome.body).group(1)
        for body in (notice.body, notice.alternatives[0][0]):
            self.assertIn("Maria Reyes", body)
            self.assertIn("new.officer", body)
            self.assertIn("maria.reyes@caraga.dilg.gov.ph", body)
            self.assertIn(Role.ENCODER.label, body)
            self.assertIn("Antonio Villanueva", body)
            self.assertNotIn(password, body)

    @override_settings(ACCOUNT_NOTIFY_EMAILS=["maria.reyes@caraga.dilg.gov.ph"])
    def test_no_notice_when_the_new_account_is_the_notify_address(self):
        from django.core import mail

        self._create()
        self.assertEqual(len(mail.outbox), 1)

    def test_the_form_no_longer_asks_for_a_password(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:user_create"))
        self.assertNotContains(response, 'name="password1"')
        self.assertNotContains(response, 'name="password2"')

    def test_an_email_address_is_required(self):
        response = self._create(email="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="new.officer").exists())

    def test_a_mail_failure_still_creates_the_account(self):
        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=OSError("mail server down"),
        ), self.assertLogs("accounts.emails", "ERROR"):
            response = self._create()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="new.officer").exists())

    def test_generated_passwords_pass_the_password_validators(self):
        from django.contrib.auth.password_validation import validate_password

        from accounts.emails import generate_temporary_password

        passwords = {generate_temporary_password() for _ in range(50)}
        self.assertEqual(len(passwords), 50)
        for password in passwords:
            validate_password(password)

    def test_a_duplicate_email_is_refused(self):
        self.staff.email = "taken@caraga.dilg.gov.ph"
        self.staff.save()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_update", args=[self.other_admin.pk]),
            {
                "username": self.other_admin.username,
                "first_name": "", "last_name": "",
                "email": "TAKEN@caraga.dilg.gov.ph",
                "position": "", "office": "", "contact_number": "",
                "role": Role.ADMIN, "is_active": "on",
            },
        )
        self.assertContains(response, "already uses this email")

    # -- self-protection -------------------------------------------------

    def test_an_administrator_cannot_change_their_own_role(self):
        """Otherwise the last administrator can lock everyone out by accident."""
        self.client.force_login(self.admin)
        self.client.post(
            reverse("accounts:user_update", args=[self.admin.pk]),
            {
                "username": "admin", "first_name": "Antonio",
                "last_name": "Villanueva", "email": "",
                "position": "", "office": "", "contact_number": "",
                "role": Role.VIEWER, "is_active": "",
            },
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Role.ADMIN)
        self.assertTrue(self.admin.is_active)

    def test_an_administrator_cannot_deactivate_themselves(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_activation", args=[self.admin.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_an_administrator_can_deactivate_another_account(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_activation", args=[self.staff.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_active)
        self.assertTrue(
            AuditEvent.objects.filter(action=Action.DEACTIVATION).exists()
        )

    # About the credentials, not the reCAPTCHA check that now stands in front
    # of them: cleared keys switch that check off (see accounts/recaptcha.py).
    @override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")
    def test_a_deactivated_account_cannot_sign_in(self):
        self.staff.is_active = False
        self.staff.save()
        self.client.post(
            reverse("accounts:login"), {"username": "staff", "password": "pw"}
        )
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 302)

    # -- password reset ---------------------------------------------------

    def test_password_reset_changes_the_password_and_is_logged(self):
        self.client.force_login(self.admin)
        AuditEvent.objects.all().delete()
        response = self.client.post(
            reverse("accounts:user_password", args=[self.staff.pk]),
            {"new_password1": "R3set-Passw0rd!", "new_password2": "R3set-Passw0rd!"},
        )
        self.assertEqual(response.status_code, 302)

        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password("R3set-Passw0rd!"))

        entry = AuditEvent.objects.get(action=Action.PASSWORD_RESET)
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.target_label, "Karl Kevin Bacon")
        self.assertNotIn("R3set-Passw0rd!", str(entry.changes) + entry.detail)


class RoleMatrixTests(TestCase):
    def test_the_matrix_reports_what_the_model_actually_grants(self):
        matrix = {row["value"]: row for row in role_matrix()}

        viewer = matrix[Role.VIEWER]["capabilities"]
        granted = {c["attribute"] for c in viewer if c["granted"]}
        self.assertEqual(granted, {"can_view"})

        # The Division Chief monitors every employee's calendar but does not
        # rewrite what they planned; changing another employee's activity is
        # reserved to the system administrator. This is the one capability the
        # ADMIN role deliberately does not hold, and the matrix must say so.
        admin = matrix[Role.ADMIN]["capabilities"]
        withheld = {c["attribute"] for c in admin if not c["granted"]}
        self.assertEqual(withheld, {"can_manage_any_activity"})
        self.assertTrue(
            next(c for c in admin if c["attribute"] == "can_supervise")["granted"]
        )

        superadmin = matrix[Role.SUPERADMIN]["capabilities"]
        self.assertTrue(all(c["granted"] for c in superadmin))

    def test_every_capability_is_a_real_property_of_the_user_model(self):
        """The matrix cannot claim a permission the model does not implement."""
        probe = User(role=Role.ADMIN)
        for attribute, _label, _description in CAPABILITIES:
            with self.subTest(capability=attribute):
                self.assertTrue(
                    hasattr(probe, attribute),
                    f"User has no attribute '{attribute}'",
                )

    def test_role_counts_reflect_the_accounts(self):
        User.objects.create_user(username="a", role=Role.ENCODER)
        User.objects.create_user(username="b", role=Role.ENCODER, is_active=False)
        row = next(r for r in role_matrix() if r["value"] == Role.ENCODER)
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["active_count"], 1)


# ---------------------------------------------------------------------------
# reCAPTCHA v3 on the sign-in form
# ---------------------------------------------------------------------------


@override_settings(
    RECAPTCHA_SITE_KEY="site-key-for-tests",
    RECAPTCHA_SECRET_KEY="secret-key-for-tests",
    RECAPTCHA_MIN_SCORE=0.5,
    RECAPTCHA_ENFORCE=True,
)
class SignInProtectionTests(TestCase):
    """
    Google is never called: `_ask_google` is replaced by the reply it would
    have given, so every branch below is the real verification code deciding.
    """

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )

    def sign_in(self, token="a-token"):
        return self.client.post(
            reverse("accounts:login"),
            {"username": "staff", "password": "pw", "recaptcha_token": token},
        )

    def signed_in(self):
        return "_auth_user_id" in self.client.session

    # -- the verdict --------------------------------------------------------

    def test_a_good_score_signs_in(self):
        with patch.object(
            recaptcha, "_ask_google",
            return_value={"success": True, "score": 0.9, "action": "login"},
        ):
            self.sign_in()
        self.assertTrue(self.signed_in())

    def test_a_low_score_is_refused_and_recorded(self):
        AuditEvent.objects.all().delete()
        with patch.object(
            recaptcha, "_ask_google",
            return_value={"success": True, "score": 0.1, "action": "login"},
        ):
            response = self.sign_in()

        self.assertFalse(self.signed_in())
        self.assertContains(response, "blocked by the automated-access check")

        entry = AuditEvent.objects.get(action=Action.LOGIN_FAILED)
        self.assertIn("reCAPTCHA", entry.detail)
        self.assertIn("staff", entry.detail)
        self.assertNotIn("pw", entry.changes)

    def test_a_missing_token_is_refused_without_calling_google(self):
        with patch.object(recaptcha, "_ask_google") as asked:
            response = self.sign_in(token="")
        asked.assert_not_called()
        self.assertFalse(self.signed_in())
        self.assertContains(response, "needs JavaScript")

    def test_a_token_minted_for_another_action_is_refused(self):
        with patch.object(
            recaptcha, "_ask_google",
            return_value={"success": True, "score": 0.9, "action": "subscribe"},
        ):
            self.sign_in()
        self.assertFalse(self.signed_in())

    def test_the_password_is_never_checked_when_the_token_is_refused(self):
        """
        The point of the check: a refused attempt must not reach authenticate(),
        or the form is still an oracle for guessing passwords.
        """
        with patch.object(
            recaptcha, "_ask_google", return_value={"success": False, "error-codes": []}
        ), patch("django.contrib.auth.authenticate") as authenticate:
            self.sign_in()
        authenticate.assert_not_called()

    # -- staying usable -----------------------------------------------------

    def test_an_outage_at_google_does_not_lock_anyone_out(self):
        with patch.object(recaptcha, "_ask_google", return_value=None):
            self.sign_in()
        self.assertTrue(self.signed_in())

    def test_a_mistyped_secret_key_does_not_lock_anyone_out(self):
        with patch.object(
            recaptcha, "_ask_google",
            return_value={"success": False, "error-codes": ["invalid-input-secret"]},
        ), self.assertLogs("accounts.recaptcha", "ERROR") as logged:
            self.sign_in()

        self.assertTrue(self.signed_in())
        # Allowed through, but never quietly: the server log has to say so.
        self.assertIn("misconfigured", logged.output[0])

    @override_settings(RECAPTCHA_ENFORCE=False)
    def test_monitor_mode_records_the_verdict_but_refuses_no_one(self):
        AuditEvent.objects.all().delete()
        with patch.object(
            recaptcha, "_ask_google",
            return_value={"success": True, "score": 0.1, "action": "login"},
        ):
            self.sign_in()

        self.assertTrue(self.signed_in())
        entry = AuditEvent.objects.get(action=Action.LOGIN_FAILED)
        self.assertIn("monitor mode", entry.detail)

    @override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")
    def test_without_keys_the_check_is_simply_off(self):
        with patch.object(recaptcha, "_ask_google") as asked:
            self.client.post(
                reverse("accounts:login"), {"username": "staff", "password": "pw"}
            )
        asked.assert_not_called()
        self.assertTrue(self.signed_in())

    # -- the page -----------------------------------------------------------

    def test_the_sign_in_page_carries_the_site_key_and_not_the_secret(self):
        page = self.client.get(reverse("accounts:login")).content.decode()
        self.assertIn("site-key-for-tests", page)
        self.assertNotIn("secret-key-for-tests", page)
        # The attribution is Google's own floating badge, drawn by that
        # script - so there is nothing of ours in the markup to assert.
        self.assertIn("recaptcha/api.js", page)
        self.assertNotIn("grecaptcha-badge", page)

    @override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")
    def test_an_unconfigured_page_does_not_call_out_to_google(self):
        """
        No keys, no request to Google - a checkout without them is not left
        waiting on a script that can never do anything. The inert hidden field
        stays; it is the loader and the site key that must be absent.
        """
        page = self.client.get(reverse("accounts:login")).content.decode()
        self.assertNotIn("recaptcha/api.js", page)
        self.assertIn('data-recaptcha-site-key=""', page)


class PrivacyNoticeTests(TestCase):
    """The Data Privacy Act notice shown after every sign-in."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF,
        )

    def test_the_notice_is_shown_after_signing_in(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, 'id="privacy-notice"')
        self.assertContains(response, "Republic Act No. 10173")

    def test_agreeing_hides_the_notice_and_is_audited(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:privacy_notice_accept"),
            {"agree": "1", "next": reverse("core:dashboard")},
        )
        self.assertRedirects(response, reverse("core:dashboard"))
        response = self.client.get(reverse("core:dashboard"))
        self.assertNotContains(response, 'id="privacy-notice"')
        self.assertTrue(AuditEvent.objects.filter(
            action=Action.PRIVACY_ACKNOWLEDGED, actor=self.user,
        ).exists())

    def test_without_the_checkbox_the_notice_stays(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:privacy_notice_accept"), {})
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, 'id="privacy-notice"')
        self.assertFalse(AuditEvent.objects.filter(
            action=Action.PRIVACY_ACKNOWLEDGED).exists())

    def test_the_notice_returns_on_the_next_sign_in(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:privacy_notice_accept"), {"agree": "1"})
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, 'id="privacy-notice"')

    def test_an_outside_next_address_is_ignored(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:privacy_notice_accept"),
            {"agree": "1", "next": "https://example.com/"},
        )
        self.assertRedirects(
            response, reverse("core:dashboard"), fetch_redirect_response=False,
        )


class ProfilePhotoTests(TestCase):
    """Uploading, replacing, serving and removing a profile photo."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="photo.owner", password="pw", first_name="Pia",
            last_name="Santos",
        )
        cls.colleague = User.objects.create_user(
            username="colleague", password="pw",
        )

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        settings_override = override_settings(
            MEDIA_ROOT=root / "media", PROTECTED_MEDIA_ROOT=root / "protected",
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.protected = root / "protected"
        self.client.force_login(self.user)

    @staticmethod
    def image_file(name="me.png", size=(600, 400), fmt="PNG", exif=None):
        buffer = io.BytesIO()
        Image.new("RGBA", size, (200, 30, 30, 128)).convert(
            "RGB" if fmt == "JPEG" else "RGBA"
        ).save(buffer, format=fmt, **({"exif": exif} if exif else {}))
        return SimpleUploadedFile(name, buffer.getvalue())

    def upload(self, upload):
        return self.client.post(reverse("accounts:profile_photo"), {"photo": upload})

    def test_upload_is_cropped_to_a_square_jpeg_in_protected_storage(self):
        response = self.upload(self.image_file())
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.photo.name.startswith("profile_photos/"))
        stored = self.protected / self.user.photo.name
        self.assertTrue(stored.exists())
        with Image.open(stored) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (photos.PHOTO_SIZE, photos.PHOTO_SIZE))

    def test_camera_metadata_is_not_kept(self):
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # Make
        self.upload(self.image_file("cam.jpg", fmt="JPEG", exif=exif.tobytes()))
        self.user.refresh_from_db()
        with Image.open(self.protected / self.user.photo.name) as image:
            self.assertEqual(dict(image.getexif()), {})

    def test_a_file_that_is_not_an_image_is_refused(self):
        response = self.upload(SimpleUploadedFile("me.png", b"not an image"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not an image")
        self.user.refresh_from_db()
        self.assertFalse(self.user.photo)

    def test_an_unsupported_format_is_refused(self):
        response = self.upload(self.image_file("me.gif", fmt="GIF"))
        self.assertContains(response, "JPEG, PNG or WebP")

    def test_replacing_deletes_the_previous_file(self):
        self.upload(self.image_file())
        self.user.refresh_from_db()
        first = self.protected / self.user.photo.name
        self.upload(self.image_file())
        self.user.refresh_from_db()
        self.assertFalse(first.exists())
        self.assertTrue((self.protected / self.user.photo.name).exists())

    def test_remove_deletes_the_file(self):
        self.upload(self.image_file())
        self.user.refresh_from_db()
        stored = self.protected / self.user.photo.name
        self.client.post(reverse("accounts:profile_photo_remove"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.photo)
        self.assertFalse(stored.exists())

    def test_colleagues_may_see_it_but_the_public_may_not(self):
        self.upload(self.image_file())
        self.user.refresh_from_db()
        url = self.user.get_photo_url()

        self.client.force_login(self.colleague)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("private", response["Cache-Control"])
        self.assertTrue(b"".join(response.streaming_content))

        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_no_photo_is_not_found(self):
        response = self.client.get(
            reverse("accounts:user_photo", args=[self.colleague.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_the_change_is_audited(self):
        self.upload(self.image_file())
        self.assertTrue(
            AuditEvent.objects.filter(
                action=Action.UPDATE, target_id=str(self.user.pk),
            ).exists()
        )
