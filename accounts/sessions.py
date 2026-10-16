"""
Where an account is signed in, and signing it out everywhere else.

Sessions live in the database (django.contrib.sessions). At each sign-in the
session notes the browser, the address and the time it began; My Profile then
lists every live session belonging to the account and can end all but the
one in use - for a phone that was lost, or a shared computer someone forgot to
sign out of.

Nothing new is stored in a table of its own: the note travels inside the
session, and ending a session is deleting its row, after which that browser is
simply signed out on its next request.
"""

from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import SESSION_KEY
from django.contrib.auth.signals import user_logged_in
from django.contrib.sessions.models import Session
from django.dispatch import receiver
from django.utils import timezone

DEVICE_KEY = "lgmed_device"


@receiver(user_logged_in)
def note_device_on_sign_in(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        note_device(request)


def note_device(request):
    """Record the browser, address and time on the session just signed in."""
    from audit.recording import client_ip

    request.session[DEVICE_KEY] = {
        "agent": request.headers.get("User-Agent", "")[:300],
        "ip": client_ip(request) or "",
        "since": timezone.now().isoformat(),
    }


@dataclass
class SignedInSession:
    key: str
    agent: str
    ip: str
    since: datetime | None
    expires: datetime
    current: bool

    @property
    def browser(self):
        """A short, readable name for the browser and system."""
        agent = self.agent
        if not agent:
            return "Unknown browser"
        browser = next(
            (name for token, name in (
                ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"), ("Safari/", "Safari"),
            ) if token in agent),
            "Browser",
        )
        system = next(
            (name for token, name in (
                ("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"),
                ("iPad", "iPad"), ("Mac OS", "macOS"), ("Linux", "Linux"),
            ) if token in agent),
            "",
        )
        return f"{browser} on {system}" if system else browser


def sessions_for(user, current_key=None):
    """Every live session of `user`, the one in use first."""
    found = []
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        data = session.get_decoded()
        if str(data.get(SESSION_KEY)) != str(user.pk):
            continue
        device = data.get(DEVICE_KEY) or {}
        since = device.get("since")
        found.append(SignedInSession(
            key=session.session_key,
            agent=device.get("agent", ""),
            ip=device.get("ip", ""),
            since=datetime.fromisoformat(since) if since else None,
            expires=session.expire_date,
            current=session.session_key == current_key,
        ))
    found.sort(key=lambda s: (not s.current, -(s.since.timestamp() if s.since else 0)))
    return found


def end_other_sessions(user, current_key):
    """Sign `user` out of every session but `current_key`. Returns how many ended."""
    others = [s.key for s in sessions_for(user, current_key) if not s.current]
    Session.objects.filter(session_key__in=others).delete()
    return len(others)
