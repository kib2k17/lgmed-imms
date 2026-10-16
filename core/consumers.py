"""
The live connection every signed-in page keeps open (static/js/app.js).

One WebSocket per page, at /ws/live/. It carries two things:

  * the system notice - when an administrator posts, changes or withdraws it,
    every open page has it within the second;
  * "you have a new notification" - to that person's pages only, and nothing
    more: no title, no text. The page then asks the status endpoint, which
    checks the session like any request, so nothing about a notification
    travels over a channel that does not.

The once-a-minute status check stays as the fallback for a page whose socket
cannot connect, and slows to every five minutes while it is connected.

Only a fully signed-in, active account is let in - a password typed but still
waiting on its second step is not signed in (accounts/mfa.py), so it is
refused like anyone else.
"""

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer

NOTICE_GROUP = "system-notice"


def user_group(user_id):
    """The group every open page of one account joins."""
    return f"user-{user_id}"


@database_sync_to_async
def current_notice():
    from administration.models import SystemSetting

    return SystemSetting.load().notice_payload()


class LiveConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not (user and user.is_authenticated and user.is_active):
            await self.close(code=4401)
            return
        await self.channel_layer.group_add(NOTICE_GROUP, self.channel_name)
        self.user_group = user_group(user.pk)
        await self.channel_layer.group_add(self.user_group, self.channel_name)
        await self.accept()
        # Whatever was posted while this page was loading or reconnecting.
        await self.send_json({"type": "notice", "notice": await current_notice()})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(NOTICE_GROUP, self.channel_name)
        if getattr(self, "user_group", None):
            await self.channel_layer.group_discard(self.user_group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # The page only listens; a keep-alive ping is answered and nothing else.
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def notice_changed(self, event):
        await self.send_json({"type": "notice", "notice": event["notice"]})

    async def notifications_changed(self, event):
        await self.send_json({"type": "notifications"})


def broadcast_notice(notice):
    """Send the system notice, as it now stands, to every open page."""
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        NOTICE_GROUP, {"type": "notice.changed", "notice": notice}
    )


def signal_notifications(user_ids):
    """
    Tell these accounts' open pages to check their notifications now.

    Best effort: a channel layer that is down must never undo the work that
    raised the notification - the page's own status check catches up.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    for user_id in set(user_ids):
        try:
            async_to_sync(layer.group_send)(
                user_group(user_id), {"type": "notifications.changed"}
            )
        except Exception:  # pragma: no cover - transport failure
            import logging

            logging.getLogger(__name__).warning(
                "Could not signal new notifications to user %s", user_id
            )
