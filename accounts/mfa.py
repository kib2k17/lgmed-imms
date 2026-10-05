"""
Two-step verification: the second half of signing in.

A correct password no longer signs anyone in who has an authenticator app, or
who is required to have one. Instead the account is parked in the session as a
*pending* sign-in, and the person is sent to enter a code (or, for an
administrator who has not enrolled yet, to enrol). Only when that succeeds does
`django.contrib.auth.login` run - so the audit log's "Signed in" entry, the
session key rotation and `last_login` all mean what they meant before: the
person is fully signed in.
"""

import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import login as auth_login
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from . import totp
from .models import MFADevice, RecoveryCode, User

PENDING_KEY = "mfa_pending"
SETUP_KEY = "mfa_setup"
FRESH_CODES_KEY = "mfa_fresh_codes"

# A pending sign-in is forgotten after this long. Ten minutes is enough to find
# a phone and install an app for a first enrolment; a password typed and then
# walked away from should not stay half-signed-in all afternoon.
PENDING_SECONDS = 10 * 60

# Wrong codes allowed within one pending sign-in before the password has to be
# entered again.
ATTEMPTS_PER_SIGNIN = 5

# Wrong codes in a row, across sign-ins, before the account's second step is
# locked for a while. With six digits and a code that changes every thirty
# seconds, this keeps guessing hopeless even for someone holding the password.
LOCKOUT_THRESHOLD = 10
LOCKOUT_DURATION = timedelta(minutes=15)

RECOVERY_CODE_COUNT = 10
# No 0/o, 1/l/i: these are read off paper and typed in by hand.
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_CODE_LENGTH = 10


# ---------------------------------------------------------------------------
# Pending sign-in
# ---------------------------------------------------------------------------


def begin(request, user, redirect_to):
    """Park an account whose password was correct, pending the second step."""
    request.session[PENDING_KEY] = {
        "user": user.pk,
        "backend": user.backend,
        # If the password changes while the sign-in is pending, the pending
        # sign-in dies with the old password.
        "hash": user.get_session_auth_hash(),
        "next": redirect_to,
        "started": time.time(),
        "attempts": 0,
    }


def pending(request):
    return request.session.get(PENDING_KEY)


def pending_user(request):
    """The account waiting on its second step, or None if there is none."""
    state = pending(request)
    if not state:
        return None
    if time.time() - state.get("started", 0) > PENDING_SECONDS:
        clear(request)
        return None
    user = User.objects.filter(pk=state.get("user"), is_active=True).first()
    if user is None or not constant_time_compare(
        user.get_session_auth_hash(), state.get("hash", "")
    ):
        clear(request)
        return None
    return user


def count_failure(request):
    """
    Record a wrong code against the pending sign-in. Returns False once the
    allowance is spent, and the sign-in has been abandoned.
    """
    state = pending(request)
    if not state:
        return False
    state["attempts"] = state.get("attempts", 0) + 1
    request.session[PENDING_KEY] = state
    if state["attempts"] >= ATTEMPTS_PER_SIGNIN:
        clear(request)
        return False
    return True


def complete(request, user):
    """Finish the sign-in. Returns where to send the person next."""
    state = pending(request) or {}
    redirect_to = state.get("next")
    auth_login(request, user, backend=state.get("backend"))
    clear(request)
    return redirect_to


def clear(request):
    request.session.pop(PENDING_KEY, None)
    request.session.pop(SETUP_KEY, None)


# ---------------------------------------------------------------------------
# Checking a code
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    ok: bool
    method: str = ""          # "app" or "recovery"
    locked: bool = False
    recovery_left: int = 0


def is_locked(device):
    return device.locked_until is not None and device.locked_until > timezone.now()


def check(user, code):
    """
    Accept a code from the authenticator app or an unused recovery code.

    The device row is locked for the duration, so two requests racing with
    the same code cannot both be accepted.
    """
    with transaction.atomic():
        device = (
            MFADevice.objects.select_for_update()
            .filter(user=user, confirmed_at__isnull=False)
            .first()
        )
        if device is None:
            return Outcome(ok=False)
        if is_locked(device):
            return Outcome(ok=False, locked=True)

        now = timezone.now()
        step = totp.match(device.secret, code, after_step=device.last_used_step)
        if step is not None:
            device.last_used_step = step
            device.last_used_at = now
            device.failed_attempts = 0
            device.locked_until = None
            device.save()
            return Outcome(ok=True, method="app")

        recovery = _find_recovery_code(user, code)
        if recovery is not None:
            recovery.used_at = now
            recovery.save(update_fields=["used_at"])
            device.last_used_at = now
            device.failed_attempts = 0
            device.locked_until = None
            device.save()
            return Outcome(
                ok=True, method="recovery", recovery_left=recovery_codes_left(user)
            )

        device.failed_attempts += 1
        locked = device.failed_attempts >= LOCKOUT_THRESHOLD
        if locked:
            device.failed_attempts = 0
            device.locked_until = now + LOCKOUT_DURATION
        device.save()
        return Outcome(ok=False, locked=locked)


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------


def setup_secret(request, user):
    """
    The key being enrolled, kept in the session until the phone proves it has
    it. Nothing is written to the database for a half-finished enrolment.
    """
    state = request.session.get(SETUP_KEY) or {}
    if state.get("user") != user.pk or not state.get("secret"):
        state = {"user": user.pk, "secret": totp.generate_secret()}
        request.session[SETUP_KEY] = state
    return state["secret"]


def enrol(user, secret, step):
    """Save a confirmed authenticator and issue fresh recovery codes."""
    with transaction.atomic():
        MFADevice.objects.update_or_create(
            user=user,
            defaults={
                "secret": secret,
                "confirmed_at": timezone.now(),
                "last_used_at": timezone.now(),
                "last_used_step": step,
                "failed_attempts": 0,
                "locked_until": None,
            },
        )
        return issue_recovery_codes(user)


def disable(user):
    with transaction.atomic():
        MFADevice.objects.filter(user=user).delete()
        RecoveryCode.objects.filter(user=user).delete()


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------


def _hash(code):
    # Recovery codes carry about fifty bits of randomness, so a keyed hash is
    # enough; a password hasher would make checking ten of them take seconds.
    return salted_hmac("lgmed.mfa.recovery", normalise_recovery(code)).hexdigest()


def normalise_recovery(code):
    return totp.normalise(code).lower()


def issue_recovery_codes(user):
    """Replace every recovery code with a new set. Returns them in plain text."""
    codes = [
        "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
        for _ in range(RECOVERY_CODE_COUNT)
    ]
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create(
        RecoveryCode(user=user, code_hash=_hash(code)) for code in codes
    )
    return [f"{c[:5]}-{c[5:]}" for c in codes]


def _find_recovery_code(user, code):
    code = normalise_recovery(code)
    if len(code) != RECOVERY_CODE_LENGTH:
        return None
    digest = _hash(code)
    for candidate in RecoveryCode.objects.select_for_update().filter(
        user=user, used_at__isnull=True
    ):
        if constant_time_compare(candidate.code_hash, digest):
            return candidate
    return None


def recovery_codes_left(user):
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


def hold_fresh_codes(request, codes, next_url=""):
    """Keep new codes for the one page that shows them."""
    request.session[FRESH_CODES_KEY] = {"codes": codes, "next": next_url or ""}


def take_fresh_codes(request):
    return request.session.pop(FRESH_CODES_KEY, None)
