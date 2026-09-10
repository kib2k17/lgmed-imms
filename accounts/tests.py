"""Tests for account administration and the role matrix."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import recaptcha
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

    def test_administrator_creates_an_account_with_a_usable_password(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "username": "new.officer",
                "first_name": "Maria", "last_name": "Reyes",
                "email": "maria.reyes@caraga.dilg.gov.ph",
                "position": "Project Evaluation Officer",
                "office": "LGMED", "contact_number": "",
                "role": Role.ENCODER, "is_active": "on",
                "password1": "Str0ng-Passw0rd!", "password2": "Str0ng-Passw0rd!",
            },
        )
        self.assertEqual(response.status_code, 302)

        created = User.objects.get(username="new.officer")
        self.assertEqual(created.role, Role.ENCODER)
        self.assertTrue(created.check_password("Str0ng-Passw0rd!"))
        self.assertTrue(
            AuditEvent.objects.filter(
                action=Action.CREATE, target_label="Maria Reyes"
            ).exists()
        )

    def test_a_weak_password_is_refused(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "username": "weak.one", "first_name": "W", "last_name": "O",
                "role": Role.VIEWER, "is_active": "on",
                "password1": "password", "password2": "password",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="weak.one").exists())

    def test_mismatched_passwords_are_refused(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "username": "mismatch", "first_name": "M", "last_name": "M",
                "role": Role.VIEWER, "is_active": "on",
                "password1": "Str0ng-Passw0rd!", "password2": "Different-P4ss!",
            },
        )
        self.assertContains(response, "do not match")
        self.assertFalse(User.objects.filter(username="mismatch").exists())

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
