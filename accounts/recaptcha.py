"""
reCAPTCHA v3 verification for the sign-in form.

v3 never shows a puzzle. The page asks Google for a token, the token travels
with the credentials, and this module asks Google what it thinks of it: a score
from 0.0 (almost certainly automated) to 1.0 (almost certainly a person).
Below ``RECAPTCHA_MIN_SCORE`` the sign-in is refused before the password is
ever checked, so a script cannot use the login form to test passwords.

Two deliberate positions:

* **An outage at Google is not evidence of a bot.** If the verification call
  cannot be made - network down, timeout, malformed reply - the attempt is
  allowed through and the failure is logged loudly. The alternative is a
  third party's bad afternoon locking an entire regional office out of its own
  records. The password check still stands behind it.

* **A missing token is a refusal.** That is what protects the form; the sign-in
  page says plainly that JavaScript is required. Set ``RECAPTCHA_ENFORCE=0``
  to run in monitor mode instead: every verdict is still recorded in the audit
  log, but nothing is refused. It is the sane way to switch the check on for
  the first time - watch the log for a week, then enforce.

The keys live in the environment, never in settings.py. See ``config/env.py``.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

# The action name the sign-in page asks for. Google echoes it back, so a token
# minted on some other page - or on a site that borrowed the public site key -
# does not open this form.
LOGIN_ACTION = "login"

# Google is telling us that *our* configuration is wrong, not that the visitor
# is suspect. Refusing everyone because the secret key was mistyped would be
# the wrong response, so these are logged as errors and allowed through.
CONFIGURATION_ERRORS = {
    "missing-input-secret",
    "invalid-input-secret",
    "invalid-keys",
    "bad-request",
}


@dataclass(frozen=True)
class Verdict:
    """The outcome of one verification."""

    allowed: bool
    score: float | None = None
    reason: str = ""

    def __str__(self):
        score = "-" if self.score is None else f"{self.score:.2f}"
        return f"{'allowed' if self.allowed else 'refused'} (score {score}): {self.reason}"


def is_enabled() -> bool:
    """True once both keys are configured. No keys, no check."""
    return bool(settings.RECAPTCHA_SITE_KEY and settings.RECAPTCHA_SECRET_KEY)


def _ask_google(token: str, remote_ip: str | None) -> dict | None:
    """The POST to Google. Returns None when the answer could not be had."""
    fields = {"secret": settings.RECAPTCHA_SECRET_KEY, "response": token}
    if remote_ip:
        fields["remoteip"] = remote_ip

    request = urllib.request.Request(
        VERIFY_URL,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=settings.RECAPTCHA_TIMEOUT
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
        logger.warning("reCAPTCHA could not be verified (%s): %s", type(error).__name__, error)
        return None


def verify(token: str, *, action: str = LOGIN_ACTION, remote_ip: str | None = None) -> Verdict:
    """
    Check one token. Never raises - every failure path returns a Verdict.
    """
    if not is_enabled():
        return Verdict(True, reason="reCAPTCHA is not configured")

    token = (token or "").strip()
    if not token:
        return Verdict(False, reason="no reCAPTCHA token was submitted")

    data = _ask_google(token, remote_ip)
    if data is None:
        return Verdict(True, reason="reCAPTCHA service unreachable; allowed")

    if not data.get("success"):
        codes = [str(code) for code in data.get("error-codes") or []]
        if CONFIGURATION_ERRORS.intersection(codes):
            logger.error(
                "reCAPTCHA is misconfigured (%s). Sign-ins are being allowed "
                "through unchecked until the keys are corrected.",
                ", ".join(codes) or "no error code",
            )
            return Verdict(True, reason=f"misconfigured: {', '.join(codes)}")
        return Verdict(False, reason=f"rejected by reCAPTCHA: {', '.join(codes) or 'no reason given'}")

    returned_action = data.get("action")
    if returned_action and returned_action != action:
        return Verdict(
            False,
            reason=f"token was minted for '{returned_action}', not '{action}'",
        )

    score = data.get("score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        # An enterprise or assessment reply without a score: nothing to judge
        # on, and success was already reported.
        return Verdict(True, reason="verified, no score returned")

    if score < settings.RECAPTCHA_MIN_SCORE:
        return Verdict(
            False,
            score=score,
            reason=f"score {score:.2f} is below the {settings.RECAPTCHA_MIN_SCORE:.2f} threshold",
        )

    return Verdict(True, score=score, reason="verified")
