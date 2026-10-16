"""Tests for the password lifecycle and who must use two-step verification."""

import datetime
import re
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import throttle
from accounts.models import Role, User
from audit.models import Action, AuditEvent

NO_RECAPTCHA = override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")
PASSWORD = "Correct-Horse-Battery-9"
NEW_PASSWORD = "Fresh-Staple-Lantern-42"


@NO_RECAPTCHA
class TemporaryPasswordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password=PASSWORD, role=Role.SUPERADMIN, is_superuser=True,
        )
        # A role that may sign in on a password alone, so these tests are
        # about the password step and nothing else.
        cls.encoder = User.objects.create_user(
            username="encoder", password=PASSWORD, role=Role.ENCODER,
            email="encoder@example.com", must_change_password=True,
        )

    def sign_in(self, username="encoder", password=PASSWORD):
        return self.client.post(
            reverse("accounts:login"), {"username": username, "password": password}
        )

    def change(self, old=PASSWORD, new=NEW_PASSWORD, **extra):
        return self.client.post(reverse("accounts:password_change"), {
            "old_password": old, "new_password1": new, "new_password2": new, **extra,
        })

    # -- where the flag comes from -------------------------------------------

    def test_a_new_account_must_change_its_emailed_password(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:user_create"), {
            "username": "new.officer", "first_name": "Maria", "last_name": "Reyes",
            "email": "maria@example.com", "role": Role.ENCODER, "is_active": "on",
            "position": "Project Evaluation Officer", "office": "LGMED",
            "contact_number": "",
        })
        self.assertTrue(User.objects.get(username="new.officer").must_change_password)
        self.assertIn("Temporary password", mail.outbox[0].body)

    def test_ordinary_accounts_are_not_flagged(self):
        self.assertFalse(User.objects.create_user(username="x", password="y").must_change_password)

    # -- being held on the change page ---------------------------------------

    def test_every_page_leads_to_the_change_page_until_it_is_done(self):
        self.sign_in()
        target = reverse("accounts:password_change")
        for url in (reverse("core:dashboard"), reverse("accounts:profile"),
                    reverse("incoming:list")):
            response = self.client.get(url)
            self.assertRedirects(response, f"{target}?next={url.replace('/', '%2F')}",
                                 fetch_redirect_response=False)

    def test_background_requests_are_refused_not_redirected(self):
        self.sign_in()
        response = self.client.get(
            reverse("notifications:status"), HTTP_ACCEPT="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_signing_out_is_still_possible(self):
        self.sign_in()
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_changing_it_clears_the_flag_and_returns_to_the_page_asked_for(self):
        self.sign_in()
        wanted = reverse("incoming:list")
        response = self.change(next=wanted)
        self.assertRedirects(response, wanted, fetch_redirect_response=False)

        self.encoder.refresh_from_db()
        self.assertFalse(self.encoder.must_change_password)
        self.assertTrue(self.encoder.check_password(NEW_PASSWORD))
        # Still signed in: the session was moved onto the new password.
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

        entry = AuditEvent.objects.get(action=Action.PASSWORD_CHANGED)
        self.assertEqual(entry.actor, self.encoder)
        self.assertNotIn(NEW_PASSWORD, entry.detail + str(entry.changes))

    def test_next_cannot_lead_off_the_site(self):
        self.sign_in()
        response = self.change(next="https://evil.example.com/")
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_the_current_password_is_required(self):
        self.sign_in()
        response = self.change(old="not-it")
        self.assertEqual(response.status_code, 200)
        self.encoder.refresh_from_db()
        self.assertTrue(self.encoder.must_change_password)

    def test_the_temporary_password_cannot_be_kept(self):
        self.sign_in()
        response = self.change(new=PASSWORD)
        self.assertContains(response, "different from the current one")
        self.encoder.refresh_from_db()
        self.assertTrue(self.encoder.must_change_password)

    def test_weak_passwords_are_refused(self):
        self.sign_in()
        self.assertEqual(self.change(new="short").status_code, 200)
        self.encoder.refresh_from_db()
        self.assertTrue(self.encoder.must_change_password)

    def test_other_sessions_are_signed_out(self):
        other = self.client_class()
        other.post(reverse("accounts:login"), {"username": "encoder", "password": PASSWORD})
        self.sign_in()
        self.change()
        response = other.get(reverse("core:dashboard"))
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))

    # -- anyone may change their own -----------------------------------------

    def test_an_unflagged_account_changes_its_password_from_the_profile(self):
        self.encoder.must_change_password = False
        self.encoder.save()
        self.sign_in()
        self.assertContains(self.client.get(reverse("accounts:profile")), "Change password")
        response = self.change()
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.encoder.refresh_from_db()
        self.assertTrue(self.encoder.check_password(NEW_PASSWORD))

    def test_an_administrators_reset_flags_the_account_again(self):
        self.encoder.must_change_password = False
        self.encoder.save()
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:user_password", args=[self.encoder.pk]))
        self.encoder.refresh_from_db()
        self.assertTrue(self.encoder.must_change_password)
        password = re.search(r"Temporary password:\s+(\S+)", mail.outbox[-1].body).group(1)
        self.assertNotIn(password, mail.outbox[-1].subject)


class WhoMustUseTwoStepVerificationTests(TestCase):
    def make(self, role, **extra):
        return User.objects.create_user(
            username=f"u{User.objects.count()}", password="pw", role=role, **extra
        )

    def test_administrators_and_publishers_must(self):
        for role in (Role.SUPERADMIN, Role.ADMIN, Role.LGMED_STAFF):
            self.assertTrue(self.make(role).mfa_required, role)

    def test_encoders_and_viewers_may_choose(self):
        for role in (Role.ENCODER, Role.VIEWER):
            self.assertFalse(self.make(role).mfa_required, role)

    def test_holding_a_verified_certificate_makes_it_required(self):
        from esira.models import SigningCertificate

        encoder = self.make(Role.ENCODER)
        now = timezone.now()

        def certificate(status, not_after):
            return SigningCertificate.objects.create(
                user=encoder, status=status, not_before=now - datetime.timedelta(days=1),
                not_after=not_after, subject="CN=Encoder", issuer="CN=Test CA",
                serial_number=str(SigningCertificate.objects.count() + 1),
                fingerprint_sha256=f"{SigningCertificate.objects.count():064d}",
                certificate_pem="-",
            )

        pending = certificate(SigningCertificate.Status.PENDING, now + datetime.timedelta(days=30))
        self.assertFalse(encoder.mfa_required)
        expired = certificate(SigningCertificate.Status.VERIFIED, now - datetime.timedelta(days=1))
        self.assertFalse(encoder.mfa_required)
        certificate(SigningCertificate.Status.VERIFIED, now + datetime.timedelta(days=30))
        self.assertTrue(encoder.mfa_required)
        del pending, expired


@override_settings(LOGIN_THROTTLE_PER_USER_IP=3, LOGIN_THROTTLE_PER_USER=6,
                   LOGIN_THROTTLE_PER_IP=10, LOGIN_THROTTLE_WINDOW=600)
class ThrottleCounterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.request = RequestFactory().post("/", REMOTE_ADDR="10.0.0.1")

    def test_failures_add_up_rather_than_overwrite(self):
        for _ in range(3):
            throttle.register_failure(self.request, "someone")
        self.assertGreater(throttle.retry_after(self.request, "someone"), 0)

    def test_the_pause_lifts_when_the_window_passes(self):
        start = 1_000_000.0
        with patch("accounts.throttle.time.time", return_value=start):
            for _ in range(3):
                throttle.register_failure(self.request, "someone")
            wait = throttle.retry_after(self.request, "someone")
        self.assertTrue(0 < wait <= 600 + 40, wait)
        with patch("accounts.throttle.time.time", return_value=start + wait):
            self.assertEqual(throttle.retry_after(self.request, "someone"), 0)
        with patch("accounts.throttle.time.time", return_value=start + wait - 41):
            self.assertGreater(throttle.retry_after(self.request, "someone"), 0)

    def test_success_clears_the_account_and_address_count(self):
        for _ in range(2):
            throttle.register_failure(self.request, "someone")
        throttle.register_success(self.request, "someone")
        throttle.register_failure(self.request, "someone")
        throttle.register_failure(self.request, "someone")
        self.assertEqual(throttle.retry_after(self.request, "someone"), 0)


@NO_RECAPTCHA
class SignedInSessionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="roaming", password=PASSWORD, role=Role.ENCODER)

    def sign_in(self, client, agent):
        client.post(
            reverse("accounts:login"), {"username": "roaming", "password": PASSWORD},
            HTTP_USER_AGENT=agent, REMOTE_ADDR="10.0.0.7",
        )

    def test_profile_lists_each_device_and_signs_the_others_out(self):
        laptop, phone = self.client, self.client_class()
        self.sign_in(phone, "Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile")
        self.sign_in(laptop, "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0")

        profile = laptop.get(reverse("accounts:profile"))
        devices = profile.context["signed_in_sessions"]
        self.assertEqual(len(devices), 2)
        self.assertTrue(devices[0].current)
        self.assertEqual(devices[0].browser, "Chrome on Windows")
        self.assertEqual(devices[1].browser, "Chrome on Android")
        self.assertEqual(devices[1].ip, "10.0.0.7")

        laptop.post(reverse("accounts:sign_out_other_sessions"))
        # The phone is signed out; the laptop is not.
        self.assertTrue(phone.get(reverse("core:dashboard"))["Location"].startswith(
            reverse("accounts:login")))
        self.assertEqual(laptop.get(reverse("core:dashboard")).status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(
            action=Action.LOGOUT, detail__startswith="Signed out of 1 other session").exists())

    def test_someone_elses_sessions_are_not_listed_or_ended(self):
        other = User.objects.create_user(username="other", password=PASSWORD, role=Role.ENCODER)
        theirs = self.client_class()
        theirs.post(reverse("accounts:login"), {"username": "other", "password": PASSWORD})
        self.sign_in(self.client, "Firefox/130.0")
        self.assertEqual(len(self.client.get(reverse("accounts:profile")).context["signed_in_sessions"]), 1)
        self.client.post(reverse("accounts:sign_out_other_sessions"))
        self.assertEqual(theirs.get(reverse("core:dashboard")).status_code, 200)
        del other
