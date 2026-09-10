"""
Tests for the audit trail.

An audit log is only worth having if it is complete, honest and tamper-evident.
These tests assert those three things: that changes made through any path are
recorded, that the entry still names the actor after the account is gone, and
that nothing in the system offers a way to edit or delete an entry.
"""

import datetime

from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from accounts.models import Role, User
from audit.models import Action, AuditEvent
from lgus.models import LGU, LGUType, Province
from monitoring.models import MonitoringActivity, MonitoringStatus


class RecordAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.province = Province.objects.create(name="Agusan del Norte")
        cls.lgu = LGU.objects.create(
            name="Cabadbaran City", lgu_type=LGUType.CITY, province=cls.province
        )
        cls.encoder = User.objects.create_user(
            username="encoder", password="pw", first_name="Rosa", last_name="Mendoza",
            role=Role.ENCODER,
        )

    def test_creating_a_record_is_logged(self):
        AuditEvent.objects.all().delete()
        activity = MonitoringActivity.objects.create(
            title="SGLG Assessment",
            lgu=self.lgu,
            monitoring_date=datetime.date(2026, 3, 2),
            monitoring_team="M. Salazar",
        )
        entry = AuditEvent.objects.get(action=Action.CREATE)
        self.assertEqual(entry.target_label, str(activity))
        self.assertEqual(entry.target_model, "Monitoring Activity")

    def test_updating_a_record_records_the_field_diff(self):
        activity = MonitoringActivity.objects.create(
            title="SGLG Assessment",
            lgu=self.lgu,
            monitoring_date=datetime.date(2026, 3, 2),
            monitoring_team="M. Salazar",
            status=MonitoringStatus.SCHEDULED,
        )
        AuditEvent.objects.all().delete()

        activity.status = MonitoringStatus.COMPLETED
        activity.monitoring_team = "M. Salazar, R. Antonio"
        activity.save()

        entry = AuditEvent.objects.get(action=Action.UPDATE)
        self.assertIn("status", entry.changes)
        # Choice values are resolved to their labels, not stored as raw codes.
        self.assertEqual(entry.changes["status"]["from"], "Scheduled")
        self.assertEqual(entry.changes["status"]["to"], "Completed")
        self.assertIn("monitoring_team", entry.changes)

    def test_a_save_that_changes_nothing_is_not_an_event(self):
        activity = MonitoringActivity.objects.create(
            title="SGLG Assessment",
            lgu=self.lgu,
            monitoring_date=datetime.date(2026, 3, 2),
            monitoring_team="M. Salazar",
        )
        AuditEvent.objects.all().delete()
        activity.save()
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_foreign_keys_are_recorded_by_name_not_by_id(self):
        other = LGU.objects.create(
            name="Buenavista", lgu_type=LGUType.MUNICIPALITY, province=self.province
        )
        activity = MonitoringActivity.objects.create(
            title="SGLG Assessment",
            lgu=self.lgu,
            monitoring_date=datetime.date(2026, 3, 2),
            monitoring_team="M. Salazar",
        )
        AuditEvent.objects.all().delete()

        activity.lgu = other
        activity.save()

        entry = AuditEvent.objects.get(action=Action.UPDATE)
        self.assertEqual(entry.changes["lgu"]["from"], "Cabadbaran City")
        self.assertEqual(entry.changes["lgu"]["to"], "Buenavista")

    def test_deleting_a_record_keeps_its_name_in_the_log(self):
        activity = MonitoringActivity.objects.create(
            title="SGLG Assessment",
            lgu=self.lgu,
            monitoring_date=datetime.date(2026, 3, 2),
            monitoring_team="M. Salazar",
        )
        label = str(activity)
        activity.delete()

        entry = AuditEvent.objects.get(action=Action.DELETE)
        self.assertEqual(entry.target_label, label)

    def test_the_entry_survives_the_actor_being_removed(self):
        """A trail that says 'deleted by nobody' is not a trail."""
        self.client.force_login(self.encoder)
        self.client.post(
            reverse("monitoring:create"),
            {
                "title": "Encoded then orphaned",
                "lgu": self.lgu.pk,
                "monitoring_date": "2026-04-01",
                "monitoring_team": "R. Mendoza",
                "status": MonitoringStatus.SCHEDULED,
            },
        )
        entry = AuditEvent.objects.filter(action=Action.CREATE).first()
        self.assertEqual(entry.actor_label, "Rosa Mendoza")

        self.encoder.delete()
        entry.refresh_from_db()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_label, "Rosa Mendoza")
        self.assertEqual(entry.actor_role, "Encoder")

    def test_actions_taken_through_a_view_are_attributed_to_the_user(self):
        self.client.force_login(self.encoder)
        AuditEvent.objects.all().delete()
        self.client.post(
            reverse("monitoring:create"),
            {
                "title": "Through the interface",
                "lgu": self.lgu.pk,
                "monitoring_date": "2026-04-01",
                "monitoring_team": "R. Mendoza",
                "status": MonitoringStatus.SCHEDULED,
            },
        )
        entry = AuditEvent.objects.get(action=Action.CREATE)
        self.assertEqual(entry.actor, self.encoder)
        self.assertEqual(entry.path, reverse("monitoring:create"))

    def test_work_outside_a_request_is_recorded_without_an_actor(self):
        """A management command must not be attributed to whoever signed in last."""
        AuditEvent.objects.all().delete()
        MonitoringActivity.objects.create(
            title="From a command",
            lgu=self.lgu,
            monitoring_date=datetime.date(2026, 3, 2),
            monitoring_team="M. Salazar",
        )
        entry = AuditEvent.objects.get(action=Action.CREATE)
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_label, "System")


class AccountAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )

    def test_password_is_never_written_to_the_log(self):
        AuditEvent.objects.all().delete()
        self.staff.set_password("a-new-secret-value")
        self.staff.save()
        for entry in AuditEvent.objects.all():
            self.assertNotIn("password", entry.changes)
            self.assertNotIn("a-new-secret-value", str(entry.changes))

    def test_role_change_is_recorded_as_its_own_action(self):
        AuditEvent.objects.all().delete()
        self.staff.role = Role.ADMIN
        self.staff.save()

        entry = AuditEvent.objects.get(action=Action.ROLE_CHANGE)
        self.assertIn("LGMED Staff", entry.detail)
        self.assertIn("Administrator", entry.detail)

    def test_deactivation_is_recorded_as_its_own_action(self):
        AuditEvent.objects.all().delete()
        self.staff.is_active = False
        self.staff.save()
        self.assertTrue(AuditEvent.objects.filter(action=Action.DEACTIVATION).exists())

    # These post real credentials; clearing the keys switches the
    # reCAPTCHA check off so the test is about the audit trail alone.
    @override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")
    def test_sign_in_and_sign_out_are_recorded(self):
        AuditEvent.objects.all().delete()
        self.client.post(
            reverse("accounts:login"), {"username": "admin", "password": "pw"}
        )
        self.client.post(reverse("accounts:logout"))
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGIN).exists())
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGOUT).exists())

    # These post real credentials; clearing the keys switches the
    # reCAPTCHA check off so the test is about the audit trail alone.
    @override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")
    def test_failed_sign_in_records_the_username_but_not_the_password(self):
        AuditEvent.objects.all().delete()
        self.client.post(
            reverse("accounts:login"),
            {"username": "admin", "password": "the-wrong-password"},
        )
        entry = AuditEvent.objects.get(action=Action.LOGIN_FAILED)
        self.assertIn("admin", entry.detail)
        self.assertNotIn("the-wrong-password", entry.detail)
        self.assertNotIn("the-wrong-password", str(entry.changes))

    def test_refused_access_is_recorded(self):
        self.client.force_login(self.staff)
        AuditEvent.objects.all().delete()
        response = self.client.get(reverse("audit:list"))
        self.assertEqual(response.status_code, 403)

        entry = AuditEvent.objects.get(action=Action.ACCESS_DENIED)
        self.assertEqual(entry.actor, self.staff)
        self.assertIn(reverse("audit:list"), entry.detail)


class AuditLogIsAppendOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )

    def test_the_log_offers_no_write_paths(self):
        """No create, edit or delete URL exists for an audit entry."""
        for name in ("audit:create", "audit:update", "audit:delete"):
            with self.subTest(url=name):
                with self.assertRaises(NoReverseMatch):
                    reverse(name)

    def test_the_list_page_does_not_offer_a_create_action(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("audit:list"))
        self.assertFalse(response.context["can_create"])

    def test_the_django_admin_refuses_to_change_entries(self):
        from django.contrib import admin as django_admin

        from .models import AuditEvent as Model

        site_admin = django_admin.site._registry[Model]
        self.assertFalse(site_admin.has_add_permission(None))
        self.assertFalse(site_admin.has_change_permission(None))
        self.assertFalse(site_admin.has_delete_permission(None))


class RetentionCommandTests(TestCase):
    def test_pruning_refuses_a_period_shorter_than_a_year(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("prune_audit_log", older_than=30, confirm=True)

    def test_a_dry_run_removes_nothing(self):
        from django.core.management import call_command

        AuditEvent.objects.create(actor_label="System", action=Action.CREATE)
        before = AuditEvent.objects.count()
        call_command("prune_audit_log", older_than=365, verbosity=0)
        self.assertEqual(AuditEvent.objects.count(), before)
