"""
Query budgets for the pages the Phase 3 performance work touched.

Each test states how many database queries a request may make. The numbers
were measured before and after the change (docs/security/SECURITY_FIXES.md,
section 6); the ceilings sit a little above the "after" figure, so the tests
fail when a later change quietly brings the old cost back.

`PRINT_FIGURES = "sql"` prints what each request actually costs, which is how
the figures were taken.
"""

import shutil
import tempfile
import time
import tracemalloc
from pathlib import Path

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from announcements.models import Announcement
from audit.models import Action, AuditEvent
from core.testing import close_response

PRINT_FIGURES = False
TEMP_MEDIA = Path(tempfile.mkdtemp(prefix="lgmed-perf-"))


def measure(client, url, **extra):
    """(status, queries, seconds, peak bytes) for one GET."""
    tracemalloc.start()
    started = time.perf_counter()
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, **extra)
        body = (
            b"".join(response.streaming_content)
            if response.streaming else response.content
        )
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    close_response(response)
    if PRINT_FIGURES == "sql":
        for q in queries.captured_queries:
            print("    ", q["sql"][:160])
    figures = (response.status_code, len(queries), elapsed, peak, len(body))
    if PRINT_FIGURES:
        print(f"\n  {url}: status={figures[0]} queries={figures[1]} "
              f"time={figures[2] * 1000:.0f}ms peak={figures[3] / 1024:.0f}KiB "
              f"bytes={figures[4]}")
    return figures


@override_settings(MEDIA_ROOT=TEMP_MEDIA, LGMED_DASHBOARD_CACHE_SECONDS=60)
class PerformanceBudgetTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="perf.admin", password="pw", role=Role.SUPERADMIN, is_superuser=True,
        )
        name = "announcements/2026/10/photo.jpg"
        (TEMP_MEDIA / name).parent.mkdir(parents=True, exist_ok=True)
        (TEMP_MEDIA / name).write_bytes(b"\xff\xd8\xff" + b"\0" * 2048)
        cls.announcement = Announcement.objects.create(
            title="Photo story", summary="s", body="b", image=name,
            is_published=True, published_on=timezone.localdate(),
        )
        cls.image_url = "/media/" + name

        # An internal file whose model sits late in core.media.SOURCES: before
        # the prefix map, every earlier source was asked about it first.
        from outgoing.models import OutgoingDocument

        reply = "outgoing/2026/01/reply.pdf"
        (TEMP_MEDIA / reply).parent.mkdir(parents=True, exist_ok=True)
        (TEMP_MEDIA / reply).write_bytes(b"%PDF-1.7 " + b"0" * 2048)
        OutgoingDocument.objects.create(
            control_code="LGMED-13 - PERF - 2026-01-05-0001", file=reply,
        )
        cls.reply_url = "/media/" + reply

    def setUp(self):
        cache.clear()

    def warm(self):
        # The settings singletons are created on first use in a fresh test
        # database; on a real one they exist and sit in the cache.
        self.client.get(reverse("core:home"))

    def test_a_public_image(self):
        self.warm()
        status, queries, *_ = measure(self.client, self.image_url)
        self.assertEqual(status, 200)
        self.assertLessEqual(queries, 3)

    def test_an_internal_file(self):
        self.client.force_login(self.admin)
        self.warm()
        status, queries, *_ = measure(self.client, self.reply_url)
        self.assertEqual(status, 200)
        self.assertLessEqual(queries, 10)

    def test_the_dashboard(self):
        self.client.force_login(self.admin)
        measure(self.client, reverse("core:dashboard"))      # fills the caches
        status, queries, *_ = measure(self.client, reverse("core:dashboard"))
        self.assertEqual(status, 200)
        # 8 for the page itself, plus one each for the viewer's own incoming
        # documents, register documents and e-SIRA steps ("My work").
        self.assertLessEqual(queries, 12)

    def test_a_large_audit_export(self):
        now = timezone.now()
        AuditEvent.objects.bulk_create([
            AuditEvent(
                action=Action.UPDATE, actor=self.admin, actor_label="perf.admin",
                target_model="announcements.Announcement", target_label=f"Item {i}",
                detail="x" * 200, timestamp=now,
            )
            for i in range(5000)
        ])
        self.client.force_login(self.admin)
        self.warm()
        status, queries, _seconds, peak, size = measure(
            self.client, reverse("audit:list") + "?export=csv"
        )
        self.assertEqual(status, 200)
        self.assertGreater(size, 5000 * 200)
        # One query per thousand rows on top of the page's own.
        self.assertLessEqual(queries, 12 + 5000 // 1000)
        # Streamed rather than built in memory first.
        response = self.client.get(reverse("audit:list") + "?export=csv")
        self.assertTrue(response.streaming)
        close_response(response)

    def test_the_audit_log_page(self):
        self.client.force_login(self.admin)
        self.warm()
        status, queries, *_ = measure(self.client, reverse("audit:list"))
        self.assertEqual(status, 200)
        self.assertLessEqual(queries, 18)

    # -- nginx sends the bytes (LGMED_ACCEL_REDIRECT) ------------------------

    def test_with_accel_redirect_nginx_is_named_the_file(self):
        self.warm()
        with override_settings(LGMED_ACCEL_REDIRECT=True):
            response = self.client.get(self.image_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Accel-Redirect"],
                         "/_internal/media/announcements/2026/10/photo.jpg")
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response["Cache-Control"], "public, max-age=3600")

    def test_with_accel_redirect_access_is_still_checked(self):
        self.warm()
        with override_settings(LGMED_ACCEL_REDIRECT=True):
            response = self.client.get(self.reply_url)      # signed out
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("X-Accel-Redirect", response)

    def test_with_accel_redirect_a_missing_file_is_still_a_404(self):
        self.warm()
        (TEMP_MEDIA / "announcements/2026/10/photo.jpg").rename(TEMP_MEDIA / "moved.jpg")
        try:
            with override_settings(LGMED_ACCEL_REDIRECT=True):
                self.assertEqual(self.client.get(self.image_url).status_code, 404)
        finally:
            (TEMP_MEDIA / "moved.jpg").rename(TEMP_MEDIA / "announcements/2026/10/photo.jpg")

    def test_with_accel_redirect_protected_files_use_their_own_location(self):
        from django.core.files.storage import storages

        from core.files import send_stored

        protected = storages["protected"]
        with override_settings(LGMED_ACCEL_REDIRECT=True):
            name = protected.save("perf/memo.pdf", __import__("io").BytesIO(b"%PDF-1.7"))
            try:
                response = send_stored(protected, name, as_attachment=True)
            finally:
                protected.delete(name)
        self.assertTrue(response["X-Accel-Redirect"].startswith("/_internal/protected/"))
        self.assertIn("attachment", response["Content-Disposition"])

    def test_without_accel_redirect_django_streams_the_file(self):
        self.warm()
        response = self.client.get(self.image_url)
        self.assertNotIn("X-Accel-Redirect", response)
        self.assertTrue(response.streaming)
        close_response(response)
