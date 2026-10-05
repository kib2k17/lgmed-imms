"""
The installable app: manifest, service worker, offline page and the
notification check it makes in the background (core/pwa.py, docs/pwa.md).
"""

import datetime
import json

from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from notifications.models import Notification


class ManifestTests(TestCase):
    def test_manifest_is_valid_and_installable(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)

        self.assertEqual(data["short_name"], "LGMED-iMMS")
        self.assertEqual(data["start_url"], reverse("pwa_launch"))
        # Unchanged identity, so copies installed before the launch page was
        # added are still the same app.
        self.assertEqual(data["id"], reverse("core:dashboard"))
        # The launch screen and the launch page are one colour.
        self.assertEqual(data["background_color"], "#0b1c30")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["display"], "standalone")
        # Chrome's installability needs a 192 and a 512 icon; Android's
        # launcher needs a maskable one.
        sizes = {(icon["sizes"], icon["purpose"]) for icon in data["icons"]}
        for needed in [("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")]:
            self.assertIn(needed, sizes)

    def test_manifest_icons_exist(self):
        data = json.loads(self.client.get("/manifest.webmanifest").content)
        from django.contrib.staticfiles import finders

        for icon in data["icons"]:
            name = icon["src"].split("/static/", 1)[1].split("?", 1)[0]
            self.assertTrue(finders.find(name), icon["src"])


class ServiceWorkerTests(TestCase):
    def test_served_from_the_root_with_root_scope(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/javascript"))
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        # A deployment must reach installed copies on their next visit.
        self.assertIn("no-cache", response["Cache-Control"])

    def test_it_never_handles_writes_or_caches_pages(self):
        body = self.client.get("/sw.js").content.decode()
        self.assertIn('if (request.method !== "GET") return;', body)
        # Pages come from the network; the only page kept is the offline one.
        self.assertNotIn("cache.put(event.request", body)
        self.assertIn(json.dumps(reverse("pwa_offline")), body)
        self.assertIn(json.dumps(reverse("pwa_launch")), body)

    def test_it_renders_valid_values(self):
        body = self.client.get("/sw.js").content.decode()
        self.assertNotIn("{{", body)
        self.assertRegex(body, r'var CACHE = "lgmed-static-[0-9a-f]{12}";')


class OfflinePageTests(TestCase):
    def test_offline_page_is_anonymous_even_when_signed_in(self):
        user = User.objects.create_user(
            username="maria", password="pw", role=Role.ADMIN,
            first_name="Maria", last_name="Unique-Surname",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("pwa_offline"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Offline mode")
        self.assertNotContains(response, "Unique-Surname")


class LaunchPageTests(TestCase):
    def test_launch_page_loads_the_dashboard_and_is_anonymous(self):
        user = User.objects.create_user(
            username="maria", password="pw", role=Role.ADMIN,
            first_name="Maria", last_name="Unique-Surname",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("pwa_launch"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "launch-ring")
        self.assertContains(response, json.dumps(reverse("core:dashboard")))
        self.assertNotContains(response, "Unique-Surname")


class InstallMarkupTests(TestCase):
    def test_system_pages_link_the_manifest_and_register_the_worker(self):
        user = User.objects.create_user(username="staff", password="pw", role=Role.LGMED_STAFF)
        self.client.force_login(user)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, "js/pwa.js")
        self.assertContains(response, 'data-sw-url="/sw.js"')
        self.assertContains(response, 'aria-label="Quick navigation"')

    def test_sign_in_page_is_installable(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'data-sw-url="/sw.js"')

    def test_public_home_page_offers_the_app(self):
        """Staff on the office network arrive at the home page first."""
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'id="pwa-install-banner"')
        self.assertContains(response, 'id="pwa-http-install"')


class NotificationStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="staff", password="pw", role=Role.LGMED_STAFF)
        cls.other = User.objects.create_user(username="other", password="pw", role=Role.LGMED_STAFF)

    def test_signed_out_is_told_so_not_redirected(self):
        response = self.client.get(reverse("notifications:status"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"authenticated": False})

    def test_reports_only_the_users_own_unread(self):
        mine = Notification.objects.create(recipient=self.user, title="Yours to review")
        Notification.objects.create(recipient=self.other, title="Someone else's")
        self.client.force_login(self.user)

        response = self.client.get(reverse("notifications:status"))
        data = response.json()
        self.assertEqual(data["unread"], 1)
        self.assertEqual([item["id"] for item in data["latest"]], [mine.pk])
        self.assertEqual(data["latest"][0]["url"], reverse("notifications:open", args=[mine.pk]))
        self.assertIn("no-store", response["Cache-Control"])

    def test_the_check_does_not_extend_the_session(self):
        """A tab left open must still time out after a working day."""
        self.client.force_login(self.user)
        key = self.client.session.session_key
        before = Session.objects.get(session_key=key).expire_date

        self.client.get(reverse("notifications:status"))
        self.assertEqual(Session.objects.get(session_key=key).expire_date, before)

    def test_ordinary_pages_still_extend_the_session(self):
        self.client.force_login(self.user)
        key = self.client.session.session_key
        soon = timezone.now() + datetime.timedelta(hours=1)
        Session.objects.filter(session_key=key).update(expire_date=soon)

        self.client.get(reverse("notifications:list"))
        self.assertGreater(Session.objects.get(session_key=key).expire_date, soon)
