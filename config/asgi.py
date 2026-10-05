"""
ASGI config for config project.

Ordinary requests go to Django as before; WebSockets go to Channels
(core/consumers.py), signed in through the same session cookie and refused from
any origin not in ALLOWED_HOSTS.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Django is set up before anything that imports models.
django_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.urls import path  # noqa: E402

from core.consumers import LiveConsumer  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter([path("ws/live/", LiveConsumer.as_asgi())])
            )
        ),
    }
)
