"""
The live connection every signed-in page keeps open (static/js/app.js).

One WebSocket per page, at /ws/live/. Today it carries the system notice: when
an administrator posts, changes or withdraws it, every open page has it within
the second instead of at its next once-a-minute status check. The status check
stays as the fallback for a page whose socket cannot connect.

Only a fully signed-in, active account is let in - a password typed but still
waiting on its second step is not signed in (accounts/mfa.py), so it is
refused like anyone else.
"""

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer

NOTICE_GROUP = "system-notice"


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
        await self.accept()
        # Whatever was posted while this page was loading or reconnecting.
        await self.send_json({"type": "notice", "notice": await current_notice()})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(NOTICE_GROUP, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # The page only listens; a keep-alive ping is answered and nothing else.
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def notice_changed(self, event):
        await self.send_json({"type": "notice", "notice": event["notice"]})


def broadcast_notice(notice):
    """Send the system notice, as it now stands, to every open page."""
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        NOTICE_GROUP, {"type": "notice.changed", "notice": notice}
    )
