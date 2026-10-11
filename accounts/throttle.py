"""
Throttling the password step of signing in.

Two-step verification protects the accounts that have it, and reCAPTCHA (when
configured) turns away most scripts. Neither stops someone from simply trying
passwords against an account without an authenticator, one careful request at
a time. This does: it counts failed sign-ins in the cache and, once a limit is
reached, refuses further attempts *before* the password is checked - so a
paused attempt reveals nothing about whether the password was right.

Three counters, each over the same window (settings.LOGIN_THROTTLE_*):

  account + address   the ordinary case - someone mistyping, or guessing at
                      one account from one machine. Tight.
  address             one machine trying many accounts (password spraying).
  account             many machines trying one account. Loose, because it is
                      the one a stranger could use to keep a colleague out; it
                      lifts on its own when the window passes, and the
                      account + address counter has usually stopped a real
                      attack long before it.

A successful sign-in clears the account + address counter. Nothing is ever
locked permanently: there is no unlock step for an administrator to forget.
"""

import hashlib
import time

from django.conf import settings
from django.core.cache import cache

from audit.recording import client_ip

_PREFIX = "lgmed:login-fail"


def _key(kind, *parts):
    # Hashed so a username full of odd characters is still a valid cache key
    # and never appears in plain text in a shared cache.
    raw = "\x1f".join(str(part).strip().lower() for part in parts)
    return f"{_PREFIX}:{kind}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _keys(username, ip):
    keys = []
    if username:
        keys.append((_key("user-ip", username, ip or "-"), settings.LOGIN_THROTTLE_PER_USER_IP))
        keys.append((_key("user", username), settings.LOGIN_THROTTLE_PER_USER))
    if ip:
        keys.append((_key("ip", ip), settings.LOGIN_THROTTLE_PER_IP))
    return keys


def _window():
    return int(settings.LOGIN_THROTTLE_WINDOW)


def _count(key):
    """Failures inside the window, from the timestamps stored under `key`."""
    now = time.time()
    return [stamp for stamp in (cache.get(key) or []) if now - stamp < _window()]


def retry_after(request, username):
    """
    Seconds until this sign-in may be attempted again, or 0 if it may now.
    """
    ip = client_ip(request)
    wait = 0
    now = time.time()
    for key, limit in _keys(username, ip):
        if limit <= 0:
            continue
        stamps = _count(key)
        if len(stamps) >= limit:
            # The oldest failure that still counts has to age out first.
            oldest = sorted(stamps)[len(stamps) - limit]
            wait = max(wait, int(oldest + _window() - now) + 1)
    return wait


def register_failure(request, username):
    ip = client_ip(request)
    now = time.time()
    for key, limit in _keys(username, ip):
        stamps = _count(key)
        stamps.append(now)
        # Keep no more than the limit needs: a flood cannot grow the entry.
        cache.set(key, stamps[-max(limit, 1):], _window())


def register_success(request, username):
    cache.delete(_key("user-ip", username, client_ip(request) or "-"))
