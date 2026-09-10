"""
Tests for the LGMED-iMMS shell and the shared module machinery.

These assert what a demonstration and an audit depend on: every route renders,
the sidebar reflects the signed-in user's role, and authorization is enforced
by the view rather than by hiding a button.
"""

import datetime

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from lgus.models import LGU, LGUType, Province
from monitoring.models import MonitoringActivity, MonitoringStatus
from programs.models import Program, ProgramCategory, ProgramStatus

PUBLIC_ROUTES = [
    "core:home",
    "core:public_about",
    "core:public_programs",
    "core:public_services",
    "core:public_announcements",
    "core:public_statistics",
    "core:public_reports",
    "core:public_documents",
    "core:public_calendar",
    "core:public_contact",
]

STAFF_ROUTES = [
    "core:dashboard",
    "core:components",
    "announcements:list",
    "accounts:profile",
    "programs:list",
    "monitoring:list",
    "incoming:list",
    "incoming:reports",
    "lgus:list",
    "services:list",
    "documents:list",
    "reports:list",
    "activities:list",
    "administration:public_site",
]

# Reached by the Division Chief and designated administrators only.
CHIEF_ROUTES = [
    "incoming:dashboard",
]

ADMIN_ROUTES = [
    "accounts:user_list",
    "accounts:role_list",
    "administration:settings",
    "audit:list",
]


def make_records():
    """A minimal but connected set of records for the view tests."""
    province = Province.objects.create(name="Agusan del Norte")
    lgu = LGU.objects.create(
        name="Cabadbaran City", lgu_type=LGUType.CITY, province=province
    )
    category = ProgramCategory.objects.create(name="Governance")
    program = Program.objects.create(
        title="Seal of Good Local Governance",
        category=category,
        start_date=datetime.date(2026, 1, 15),
        status=ProgramStatus.ACTIVE,
    )
    activity = MonitoringActivity.objects.create(
        title="SGLG Assessment",
        lgu=lgu,
        program=program,
        monitoring_date=datetime.date(2026, 3, 2),
        monitoring_team="M. Salazar",
        status=MonitoringStatus.COMPLETED,
    )
    return province, lgu, category, program, activity


class PublicSiteTests(TestCase):
    def test_public_pages_render_without_authentication(self):
        for name in PUBLIC_ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_footer_carries_office_contact_details(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Purok 1-A, Brgy. Doongan, Butuan City, 8600")
        self.assertContains(response, "(085) 975-9830 to 34")

    def test_public_site_shows_only_published_records(self):
        _, _, category, program, _ = make_records()
        Program.objects.create(
            title="Unpublished draft program",
            category=category,
            start_date=datetime.date(2026, 2, 1),
            status=ProgramStatus.PENDING,
        )
        response = self.client.get(reverse("core:public_programs"))
        self.assertContains(response, program.title)
        self.assertNotContains(response, "Unpublished draft program")

    def test_login_page_renders(self):
        self.assertEqual(self.client.get(reverse("accounts:login")).status_code, 200)

    def test_login_page_carries_the_agency_identity(self):
        """
        Regression: Django's LoginView injects its own `site` into the context,
        which silently blanked every identity value on this page.
        """
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, "LGMED-iMMS")
        self.assertContains(response, "Department of the Interior and Local Government")
        self.assertContains(response, "RegionalOffice@caraga.dilg.gov.ph")

    def test_the_official_seal_is_used_where_it_is_available(self):
        for name in ("core:home", "accounts:login"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, "img/dilg-logo.png")


class AuthenticatedShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_records()
        cls.staff = User.objects.create_user(
            username="lgmed.staff",
            password="test-password-1",
            first_name="Karl Kevin",
            last_name="Bacon",
            position="Information Systems Analyst",
            role=Role.LGMED_STAFF,
        )
        cls.admin = User.objects.create_user(
            username="lgmed.admin", password="test-password-2", role=Role.ADMIN
        )
        cls.viewer = User.objects.create_user(
            username="lgmed.viewer", password="test-password-3", role=Role.VIEWER
        )

    def test_staff_routes_require_authentication(self):
        for name in STAFF_ROUTES:
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_staff_routes_render_for_signed_in_user(self):
        self.client.force_login(self.staff)
        for name in STAFF_ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_dashboard_shows_account_and_role(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "Karl Kevin Bacon")
        self.assertContains(response, "Information Systems Analyst")
        self.assertContains(response, "Regional monitoring and evaluation overview")

    def test_dashboard_counts_come_from_the_records(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core:dashboard"))
        cards = {c["label"]: c["value"] for c in response.context["summary_cards"]}
        self.assertEqual(cards["Total Programs"], Program.objects.count())
        self.assertEqual(cards["Registered LGUs"], LGU.objects.count())

    def test_only_one_sidebar_item_is_active(self):
        """/app/ prefixes every module URL, so this guards the longest-prefix match."""
        self.client.force_login(self.staff)
        response = self.client.get(reverse("monitoring:list"))
        active = [
            item["label"]
            for section in response.context["sidebar_sections"]
            for item in section["items"]
            if item["is_active"]
        ]
        self.assertEqual(active, ["Monitoring"])

    def test_administration_section_hidden_from_non_administrators(self):
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(reverse("core:dashboard")), "Audit Logs")

    def test_administration_section_shown_to_administrators(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("core:dashboard")), "Audit Logs")

    def test_administration_urls_are_enforced_server_side(self):
        """Hiding the link is not the control - the view refuses the request."""
        self.client.force_login(self.viewer)
        for name in ADMIN_ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_the_incoming_dashboard_is_refused_to_those_who_cannot_assign(self):
        """Reviewing and assigning incoming documents is the Chief's alone."""
        self.client.force_login(self.staff)
        for name in CHIEF_ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_the_incoming_dashboard_opens_for_the_division_chief(self):
        self.client.force_login(self.admin)
        for name in CHIEF_ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_administrators_reach_administration_modules(self):
        self.client.force_login(self.admin)
        for name in ADMIN_ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class RolePermissionTests(TestCase):
    def test_permission_matrix(self):
        cases = [
            (Role.SUPERADMIN, True, True, True, True),
            (Role.ADMIN, True, True, True, True),
            (Role.LGMED_STAFF, False, True, True, False),
            (Role.ENCODER, False, True, False, False),
            (Role.VIEWER, False, False, False, False),
        ]
        for role, administer, encode, approve, delete in cases:
            with self.subTest(role=role):
                user = User(username=f"u-{role}", role=role)
                self.assertEqual(user.can_administer, administer)
                self.assertEqual(user.can_encode, encode)
                self.assertEqual(user.can_approve, approve)
                self.assertEqual(user.can_delete, delete)


class StatusVocabularyTests(TestCase):
    def test_record_values_map_onto_the_five_tones(self):
        from core.status import resolve_status

        self.assertEqual(resolve_status("Active"), "success")
        self.assertEqual(resolve_status("for_review"), "warning")
        self.assertEqual(resolve_status("overdue"), "danger")
        self.assertEqual(resolve_status("in_progress"), "info")
        self.assertEqual(resolve_status("archived"), "neutral")
        self.assertEqual(resolve_status(""), "neutral")
        self.assertEqual(resolve_status("something-unmapped"), "neutral")

    def test_every_model_status_value_is_mapped(self):
        """A new status must not silently fall back to grey."""
        from core.status import STATUS_MAP, STATUS_STYLES
        from activities.models import ActivityType  # noqa: F401
        from documents.models import DocumentStatus
        from incoming.models import IncomingStatus
        from lgus.models import ComplianceStatus
        from reports.models import ReportStatus
        from updates.models import PeriodStatus, UpdateStatus, WayForwardStatus

        known = set(STATUS_MAP) | set(STATUS_STYLES)
        values = set()
        for choices in (
            ProgramStatus.values,
            MonitoringStatus.values,
            DocumentStatus.values,
            ReportStatus.values,
            IncomingStatus.values,
            PeriodStatus.values,
            UpdateStatus.values,
            WayForwardStatus.values,
        ):
            values.update(v.lower() for v in choices)
        # Compliance statuses are mapped through LGU.compliance_tone.
        values.update({"compliant", "partial", "non_compliant", "not_started"})
        self.assertFalse(
            values - known,
            f"unmapped status values: {sorted(values - known)}",
        )
        self.assertTrue(ComplianceStatus.choices)

    def test_badge_carries_a_text_label_not_only_colour(self):
        from django.template import Context, Template

        rendered = Template('{% load ui %}{% status_badge "approved" %}').render(
            Context({})
        )
        self.assertIn("Approved", rendered)
        self.assertIn("<svg", rendered)
