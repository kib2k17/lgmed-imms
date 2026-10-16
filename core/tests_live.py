"""The live WebSocket connection (core/consumers.py)."""

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.core.cache import cache
from django.test import TransactionTestCase
from django.urls import reverse

from accounts.models import Role, User
from administration.models import SystemSetting
from config.asgi import application


class LiveConnectionTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin", password="pw", role=Role.ADMIN
        )
        self.staff = User.objects.create_user(
            username="staff", password="pw", role=Role.LGMED_STAFF
        )

    def _headers(self, user=None, client=None):
        headers = [(b"origin", b"http://localhost"), (b"host", b"localhost")]
        if user is not None:
            client = client or self.client
            client.force_login(user)
            session = client.cookies[settings.SESSION_COOKIE_NAME].value
            headers.append(
                (b"cookie", f"{settings.SESSION_COOKIE_NAME}={session}".encode())
            )
        return headers

    def _post_notice(self, message):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("administration:settings"),
            {
                "records_per_page": 15,
                "session_notice_minutes": 5,
                "notice_message": message,
                "notice_level": "danger",
                "notice_takeover": "on",
                "public_site_enabled": "on",
            },
        )

    async def test_a_visitor_who_is_not_signed_in_is_refused(self):
        socket = WebsocketCommunicator(application, "/ws/live/", headers=self._headers())
        connected, code = await socket.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_a_socket_from_another_site_is_refused(self):
        headers = await sync_to_async(self._headers)(self.staff)
        headers[0] = (b"origin", b"http://evil.example")
        socket = WebsocketCommunicator(application, "/ws/live/", headers=headers)
        connected, _ = await socket.connect()
        self.assertFalse(connected)

    async def test_an_announcement_reaches_an_open_page_at_once(self):
        headers = await sync_to_async(self._headers)(self.staff)
        socket = WebsocketCommunicator(application, "/ws/live/", headers=headers)
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        # On connecting, the page is told the notice as it stands: none.
        self.assertEqual(await socket.receive_json_from(), {"type": "notice", "notice": None})

        await sync_to_async(self._post_notice)("Evacuate the building.")

        message = await socket.receive_json_from(timeout=2)
        self.assertEqual(message["type"], "notice")
        self.assertEqual(message["notice"]["message"], "Evacuate the building.")
        self.assertTrue(message["notice"]["takeover"])
        key = await sync_to_async(lambda: SystemSetting.load().notice_key)()
        self.assertEqual(message["notice"]["key"], key)
        await socket.disconnect()

    async def test_a_new_notification_tells_only_its_recipients_pages(self):
        from notifications.service import notify

        staff_socket = WebsocketCommunicator(
            application, "/ws/live/", headers=await sync_to_async(self._headers)(self.staff),
        )
        self.assertTrue((await staff_socket.connect())[0])
        await staff_socket.receive_json_from()                    # the notice on connect
        admin_headers = await sync_to_async(
            lambda: self._headers(self.admin, client=self.client_class())
        )()
        admin_socket = WebsocketCommunicator(application, "/ws/live/", headers=admin_headers)
        self.assertTrue((await admin_socket.connect())[0])
        await admin_socket.receive_json_from()

        await sync_to_async(notify)([self.staff], title="A document was assigned to you")

        # Only a prompt to look: the title stays behind the status endpoint.
        self.assertEqual(await staff_socket.receive_json_from(timeout=2), {"type": "notifications"})
        self.assertTrue(await admin_socket.receive_nothing(timeout=0.5))
        await staff_socket.disconnect()
        await admin_socket.disconnect()
