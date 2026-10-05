"""Tests for Menu Permissions: sidebar modules by role and by account."""

from django.test import TestCase
from django.urls import reverse

from accounts import menu_access
from accounts.models import Role, RoleModuleAccess, User, UserModuleAccess
from audit.models import Action, AuditEvent
from core.navigation import build_sidebar


def sidebar_keys(user):
    # Reloaded, as every request does: the answer is cached on the object.
    user = User.objects.get(pk=user.pk)
    return {item["key"] for section in build_sidebar(user)
            for item in section["items"]}


class MenuAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superadmin = User.objects.create_user(
            username="ict", password="pw", role=Role.SUPERADMIN,
        )
        cls.admin = User.objects.create_user(
            username="chief", password="pw", role=Role.ADMIN,
        )
        cls.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF,
        )
        cls.viewer = User.objects.create_user(
            username="viewer", password="pw", role=Role.VIEWER,
        )

    def close(self, module, role):
        RoleModuleAccess.objects.create(module=module, role=role, allowed=False)

    # -- resolution -----------------------------------------------------

    def test_every_module_is_open_without_a_rule(self):
        self.assertIn("analytics", sidebar_keys(self.viewer))
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.get(reverse("analytics:index")).status_code, 200
        )

    def test_a_module_closed_to_a_role_is_hidden_and_refused(self):
        self.close("analytics", Role.VIEWER)
        self.assertNotIn("analytics", sidebar_keys(self.viewer))
        self.assertIn("analytics", sidebar_keys(self.staff))

        self.client.force_login(self.viewer)
        response = self.client.get(reverse("analytics:index"))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            AuditEvent.objects.filter(
                action=Action.ACCESS_DENIED, actor=self.viewer
            ).exists()
        )

    def test_only_the_closed_module_of_a_namespace_is_refused(self):
        self.close("ppa_queue", Role.LGMED_STAFF)
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("programs:queue")).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("programs:list")).status_code, 200
        )

    def test_an_account_rule_overrides_its_role(self):
        self.close("analytics", Role.VIEWER)
        UserModuleAccess.objects.create(
            module="analytics", user=self.viewer, allowed=True
        )
        UserModuleAccess.objects.create(
            module="reports", user=self.viewer, allowed=False
        )
        keys = sidebar_keys(self.viewer)
        self.assertIn("analytics", keys)
        self.assertNotIn("reports", keys)

    def test_opening_a_module_cannot_exceed_the_role(self):
        UserModuleAccess.objects.create(
            module="ppa_queue", user=self.viewer, allowed=True
        )
        self.assertNotIn("ppa_queue", sidebar_keys(self.viewer))

    def test_the_system_administrator_is_never_restricted(self):
        self.close("analytics", Role.SUPERADMIN)
        UserModuleAccess.objects.create(
            module="esira", user=self.superadmin, allowed=False
        )
        keys = sidebar_keys(self.superadmin)
        self.assertIn("analytics", keys)
        self.assertIn("esira", keys)
        self.client.force_login(self.superadmin)
        self.assertEqual(
            self.client.get(reverse("analytics:index")).status_code, 200
        )

    def test_a_closed_dashboard_sends_the_account_to_its_first_module(self):
        self.close("dashboard", Role.VIEWER)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(
            response, reverse("programs:list"), fetch_redirect_response=False
        )

    # -- the management pages -------------------------------------------

    def test_only_the_system_administrator_manages_menu_permissions(self):
        for account in (self.admin, self.staff):
            self.client.force_login(account)
            for url in (
                reverse("accounts:menu_permissions"),
                reverse("accounts:user_menu_permissions", args=[self.viewer.pk]),
            ):
                with self.subTest(account=account.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
        self.assertNotIn("menu_permissions", sidebar_keys(self.admin))
        self.assertIn("menu_permissions", sidebar_keys(self.superadmin))

    def test_saving_the_role_matrix(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(
            self.client.get(reverse("accounts:menu_permissions")).status_code,
            200,
        )
        # Everything ticked except Analytics for Viewers.
        ticks = [
            f"{item['key']}:{role}"
            for item in menu_access.managed_items()
            for role, _ in menu_access.managed_roles()
            if (item["key"], role) != ("analytics", Role.VIEWER)
        ]
        response = self.client.post(
            reverse("accounts:menu_permissions"), {"access": ticks}
        )
        self.assertRedirects(response, reverse("accounts:menu_permissions"))
        self.assertEqual(
            list(RoleModuleAccess.objects.values_list("module", "role", "allowed")),
            [("analytics", Role.VIEWER, False)],
        )
        self.assertNotIn("analytics", sidebar_keys(self.viewer))

        # Reopening it keeps the row, now open.
        ticks.append(f"analytics:{Role.VIEWER}")
        self.client.post(reverse("accounts:menu_permissions"), {"access": ticks})
        self.assertTrue(
            RoleModuleAccess.objects.get(module="analytics", role=Role.VIEWER).allowed
        )
        self.assertIn("analytics", sidebar_keys(self.viewer))

    def test_saving_an_account_and_returning_it_to_its_role(self):
        self.client.force_login(self.superadmin)
        url = reverse("accounts:user_menu_permissions", args=[self.staff.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.post(url, {"module_calendar": "deny"})
        self.assertFalse(
            UserModuleAccess.objects.get(user=self.staff, module="calendar").allowed
        )
        self.assertNotIn("calendar", sidebar_keys(self.staff))
        self.assertTrue(
            AuditEvent.objects.filter(
                action=Action.UPDATE, detail__startswith="Menu permissions"
            ).exists()
        )

        self.client.post(url, {"module_calendar": "inherit"})
        self.assertFalse(UserModuleAccess.objects.filter(user=self.staff).exists())

    def test_a_system_administrator_account_cannot_be_restricted(self):
        self.client.force_login(self.superadmin)
        url = reverse("accounts:user_menu_permissions", args=[self.superadmin.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            self.client.post(url, {"module_esira": "deny"}).status_code, 403
        )
        self.assertFalse(UserModuleAccess.objects.exists())
