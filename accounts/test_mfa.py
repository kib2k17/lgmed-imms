"""Tests for two-step verification."""

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import mfa, totp
from accounts.models import MFADevice, RecoveryCode, Role, User
from audit.models import Action, AuditEvent


class TOTPTests(TestCase):
    # RFC 6238, appendix B: the SHA-1 test key, truncated to six digits.
    RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    def test_codes_match_the_rfc_vectors(self):
        for when, code in [(59, "287082"), (1111111109, "081804"),
                           (1234567890, "005924"), (2000000000, "279037")]:
            self.assertEqual(
                totp.match(self.RFC_SECRET, code, now=when), when // 30
            )

    def test_a_neighbouring_step_is_accepted_but_no_further(self):
        now = 1234567890
        before = totp._code_at(self.RFC_SECRET, now // 30 - 1)
        long_before = totp._code_at(self.RFC_SECRET, now // 30 - 3)
        self.assertIsNotNone(totp.match(self.RFC_SECRET, before, now=now))
        self.assertIsNone(totp.match(self.RFC_SECRET, long_before, now=now))

    def test_a_code_is_good_once(self):
        now = 1234567890
        step = totp.match(self.RFC_SECRET, "005924", now=now)
        self.assertIsNone(
            totp.match(self.RFC_SECRET, "005924", after_step=step, now=now)
        )

    def test_spaces_are_ignored_and_rubbish_refused(self):
        self.assertIsNotNone(totp.match(self.RFC_SECRET, "005 924", now=1234567890))
        for junk in ("", "abcdef", "12345", "1234567"):
            self.assertIsNone(totp.match(self.RFC_SECRET, junk, now=1234567890))


# Real credentials are posted; clearing the keys switches the reCAPTCHA check
# off so these tests are about the second step alone.
@override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")
class TwoStepSignInTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )
        cls.other_admin = User.objects.create_user(
            username="admin2", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )

    # -- helpers ------------------------------------------------------------

    def enrol(self, user):
        secret = totp.generate_secret()
        codes = mfa.enrol(user, secret, step=totp.current_step() - 5)
        return secret, codes

    def now_code(self, secret):
        return totp._code_at(secret, totp.current_step())

    def sign_in(self, username, **extra):
        return self.client.post(
            reverse("accounts:login"),
            {"username": username, "password": "pw", **extra},
        )

    def verify(self, code, **extra):
        return self.client.post(reverse("accounts:mfa_verify"), {"code": code, **extra})

    def signed_in(self):
        return "_auth_user_id" in self.client.session

    # -- who is asked -------------------------------------------------------

    def test_staff_without_mfa_sign_in_with_a_password(self):
        self.sign_in("staff")
        self.assertTrue(self.signed_in())

    def test_an_administrator_must_enrol_before_being_signed_in(self):
        response = self.sign_in("admin")
        self.assertRedirects(response, reverse("accounts:mfa_setup"))
        self.assertFalse(self.signed_in())
        self.assertFalse(
            AuditEvent.objects.filter(action=Action.LOGIN, actor=self.admin).exists()
        )

    def test_an_administrator_enrols_during_sign_in(self):
        self.sign_in("admin")
        response = self.client.get(reverse("accounts:mfa_setup"))
        self.assertContains(response, "<svg")
        secret = self.client.session[mfa.SETUP_KEY]["secret"]

        response = self.client.post(
            reverse("accounts:mfa_setup"), {"code": self.now_code(secret)}
        )
        # Not followed: fetching the page would use up its one showing.
        self.assertRedirects(
            response, reverse("accounts:mfa_recovery_codes"),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.signed_in())
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.mfa_enabled)
        self.assertEqual(mfa.recovery_codes_left(self.admin), 10)

        # Shown once, then gone.
        self.assertContains(
            self.client.get(reverse("accounts:mfa_recovery_codes")),
            "I have saved my codes",
        )
        self.assertRedirects(
            self.client.get(reverse("accounts:mfa_recovery_codes")),
            reverse("accounts:profile"),
        )

    def test_a_wrong_code_does_not_enrol(self):
        self.sign_in("admin")
        self.client.get(reverse("accounts:mfa_setup"))
        response = self.client.post(reverse("accounts:mfa_setup"), {"code": "000000"})
        self.assertContains(response, "does not match")
        self.assertFalse(MFADevice.objects.filter(user=self.admin).exists())
        self.assertFalse(self.signed_in())

    def test_the_password_alone_cannot_replace_an_enrolled_phone(self):
        self.enrol(self.admin)
        self.sign_in("admin")
        response = self.client.get(reverse("accounts:mfa_setup"))
        self.assertRedirects(response, reverse("accounts:mfa_verify"))

    def test_the_setup_page_needs_a_password_first(self):
        response = self.client.get(reverse("accounts:mfa_setup"))
        self.assertRedirects(response, reverse("accounts:login"))

    # -- the second step ----------------------------------------------------

    def test_an_enrolled_account_is_asked_for_a_code(self):
        secret, _ = self.enrol(self.staff)
        response = self.sign_in("staff")
        self.assertRedirects(response, reverse("accounts:mfa_verify"))
        self.assertFalse(self.signed_in())

        response = self.verify(self.now_code(secret))
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertTrue(self.signed_in())
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGIN).exists())

    def test_next_survives_the_second_step(self):
        secret, _ = self.enrol(self.staff)
        target = reverse("accounts:profile")
        self.sign_in("staff", next=target)
        self.assertRedirects(self.verify(self.now_code(secret)), target)

    def test_a_wrong_code_is_refused_and_recorded(self):
        self.enrol(self.staff)
        self.sign_in("staff")
        AuditEvent.objects.all().delete()
        response = self.verify("000000")
        self.assertContains(response, "not correct")
        self.assertFalse(self.signed_in())
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGIN_FAILED).exists())

    def test_a_code_cannot_be_used_twice(self):
        secret, _ = self.enrol(self.staff)
        code = self.now_code(secret)
        self.sign_in("staff")
        self.verify(code)
        self.assertTrue(self.signed_in())
        self.client.post(reverse("accounts:logout"))

        self.sign_in("staff")
        self.verify(code)
        self.assertFalse(self.signed_in())

    def test_too_many_wrong_codes_abandon_the_sign_in(self):
        self.enrol(self.staff)
        self.sign_in("staff")
        for _ in range(mfa.ATTEMPTS_PER_SIGNIN):
            response = self.verify("000000")
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn(mfa.PENDING_KEY, self.client.session)

    def test_repeated_failures_across_sign_ins_lock_the_account(self):
        secret, _ = self.enrol(self.staff)
        for _ in range(mfa.LOCKOUT_THRESHOLD // mfa.ATTEMPTS_PER_SIGNIN):
            self.sign_in("staff")
            for _ in range(mfa.ATTEMPTS_PER_SIGNIN):
                self.verify("000000")

        self.sign_in("staff")
        self.verify(self.now_code(secret))
        self.assertFalse(self.signed_in())

    def test_a_recovery_code_signs_in_once(self):
        _, codes = self.enrol(self.staff)
        self.sign_in("staff")
        self.verify(codes[0].upper(), recovery="1")
        self.assertTrue(self.signed_in())
        self.assertEqual(mfa.recovery_codes_left(self.staff), 9)
        self.assertTrue(
            AuditEvent.objects.filter(action=Action.MFA_RECOVERY_USED).exists()
        )
        self.client.post(reverse("accounts:logout"))

        self.sign_in("staff")
        self.verify(codes[0])
        self.assertFalse(self.signed_in())

    def test_recovery_codes_are_not_stored_in_plain_text(self):
        _, codes = self.enrol(self.staff)
        stored = " ".join(RecoveryCode.objects.values_list("code_hash", flat=True))
        for code in codes:
            self.assertNotIn(code.replace("-", ""), stored)

    def test_a_password_change_kills_a_pending_sign_in(self):
        secret, _ = self.enrol(self.staff)
        self.sign_in("staff")
        self.staff.set_password("S0mething-else!")
        self.staff.save()
        response = self.verify(self.now_code(secret))
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertFalse(self.signed_in())

    def test_the_django_admin_login_is_not_a_side_door(self):
        response = self.client.get("/django-admin/login/?next=/django-admin/")
        self.assertRedirects(
            response, reverse("accounts:login") + "?next=/django-admin/",
            fetch_redirect_response=False,
        )

    # -- managing it from My Profile ---------------------------------------

    def test_staff_turn_it_on_from_their_profile(self):
        self.client.force_login(self.staff)
        self.assertContains(
            self.client.get(reverse("accounts:profile")),
            "Set up two-step verification",
        )
        self.client.get(reverse("accounts:mfa_setup"))
        secret = self.client.session[mfa.SETUP_KEY]["secret"]
        self.client.post(reverse("accounts:mfa_setup"), {"code": self.now_code(secret)})
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.mfa_enabled)
        self.assertTrue(AuditEvent.objects.filter(action=Action.MFA_ENABLED).exists())
        self.assertContains(self.client.get(reverse("accounts:profile")), "New recovery codes")

    def test_turning_it_off_needs_a_code(self):
        secret, _ = self.enrol(self.staff)
        self.client.force_login(self.staff)
        self.client.post(reverse("accounts:mfa_disable"), {"code": "000000"})
        self.assertTrue(MFADevice.objects.filter(user=self.staff).exists())

        self.client.post(reverse("accounts:mfa_disable"), {"code": self.now_code(secret)})
        self.assertFalse(MFADevice.objects.filter(user=self.staff).exists())
        self.assertEqual(mfa.recovery_codes_left(self.staff), 0)
        self.assertTrue(AuditEvent.objects.filter(action=Action.MFA_DISABLED).exists())

    def test_an_administrator_turning_it_off_is_sent_to_set_up_again(self):
        secret, _ = self.enrol(self.admin)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:mfa_disable"), {"code": self.now_code(secret)}
        )
        self.assertRedirects(response, reverse("accounts:mfa_setup"))

    def test_renewing_recovery_codes_replaces_the_old_ones(self):
        secret, old = self.enrol(self.staff)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("accounts:mfa_regenerate_codes"), {"code": self.now_code(secret)}
        )
        self.assertRedirects(response, reverse("accounts:mfa_recovery_codes"))
        self.assertIsNone(mfa._find_recovery_code(self.staff, old[0]))
        self.assertEqual(mfa.recovery_codes_left(self.staff), 10)

    # -- an administrator resetting a lost phone ---------------------------

    def test_an_administrator_resets_another_account(self):
        self.enrol(self.staff)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("accounts:user_detail", args=[self.staff.pk]))
        self.assertContains(page, "Reset two-step verification")

        self.client.post(reverse("accounts:user_mfa_reset", args=[self.staff.pk]))
        self.assertFalse(MFADevice.objects.filter(user=self.staff).exists())
        entry = AuditEvent.objects.get(action=Action.MFA_DISABLED)
        self.assertEqual(entry.actor, self.admin)

    def test_an_administrator_cannot_reset_their_own_here(self):
        self.enrol(self.admin)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_mfa_reset", args=[self.admin.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(MFADevice.objects.filter(user=self.admin).exists())

    def test_staff_cannot_reset_anyone(self):
        self.enrol(self.other_admin)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("accounts:user_mfa_reset", args=[self.other_admin.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(MFADevice.objects.filter(user=self.other_admin).exists())
