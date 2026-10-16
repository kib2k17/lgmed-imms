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


# Failures are counted in buckets, each a fifteenth of the window (a minute at
# the default fifteen), and a bucket is only ever incremented - one atomic
# cache operation per failure. Storing a list of timestamps instead meant
# reading it, appending and writing it back, so two attempts landing together
# could each write a list missing the other's failure.
_BUCKETS_PER_WINDOW = 15


def _bucket_seconds():
    return max(1, -(-_window() // _BUCKETS_PER_WINDOW))


def _buckets(now):
    """The bucket indexes the window covers at `now`, oldest first."""
    size = _bucket_seconds()
    current = int(now // size)
    span = -(-_window() // size)
    return list(range(current - span + 1, current + 1))


def _bucket_key(key, index):
    return f"{key}:{index}"


def _counts(key, now):
    """[(bucket index, failures)] inside the window, oldest first."""
    indexes = _buckets(now)
    stored = cache.get_many([_bucket_key(key, i) for i in indexes])
    return [(i, int(stored.get(_bucket_key(key, i)) or 0)) for i in indexes]


def retry_after(request, username):
    """
    Seconds until this sign-in may be attempted again, or 0 if it may now.
    """
    ip = client_ip(request)
    wait = 0
    now = time.time()
    size = _bucket_seconds()
    span = len(_buckets(now))
    for key, limit in _keys(username, ip):
        if limit <= 0:
            continue
        counts = _counts(key, now)
        excess = sum(n for _, n in counts) - limit + 1
        if excess <= 0:
            continue
        # The oldest buckets age out first: wait until enough have gone that
        # one more attempt would be under the limit.
        for index, n in counts:
            excess -= n
            if excess <= 0:
                wait = max(wait, int((index + span) * size - now) + 1)
                break
    return wait


def register_failure(request, username):
    ip = client_ip(request)
    now = time.time()
    index = _buckets(now)[-1]
    # Kept a bucket longer than the window, so it is still there to be read
    # for as long as the window covers it.
    timeout = _window() + _bucket_seconds()
    for key, _limit in _keys(username, ip):
        bucket = _bucket_key(key, index)
        cache.add(bucket, 0, timeout)
        try:
            cache.incr(bucket)
        except ValueError:
            # Expired between the two calls: start it again.
            cache.set(bucket, 1, timeout)


def register_success(request, username):
    key = _key("user-ip", username, client_ip(request) or "-")
    cache.delete_many([_bucket_key(key, i) for i in _buckets(time.time())])
