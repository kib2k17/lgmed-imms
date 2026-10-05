"""
Time-based one-time passwords (RFC 6238), the codes an authenticator app shows.

The algorithm is a dozen lines over the standard library, so it is written out
here rather than pulled in as a dependency: every authenticator app on the
market - Google, Microsoft, Authy, 1Password - speaks exactly this dialect
(SHA-1, six digits, thirty-second steps), and anything more configurable would
only be more ways to enrol a phone that then cannot sign in.

Only the QR code needs a library (segno, pure Python, no dependencies of its
own). It is drawn on the server as inline SVG, so the secret never leaves this
system on its way to the phone - a QR code rendered by a third-party web
service would hand that service the key to the account.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30

# How many steps either side of "now" a code is still accepted for. One step
# covers a phone clock that is up to thirty seconds out, and a code typed just
# as it rolled over. Wider than that and a code overheard on screen stays usable
# for minutes.
DRIFT_STEPS = 1


def generate_secret():
    """A new 160-bit key, base32-encoded the way authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _code_at(secret, step):
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now=None):
    return int((time.time() if now is None else now) // STEP_SECONDS)


def normalise(code):
    """What the person typed, without the spaces some apps display."""
    return "".join((code or "").split()).replace("-", "")


def match(secret, code, *, after_step=None, now=None):
    """
    The time step `code` belongs to, or None if it is not valid now.

    `after_step` is the step of the last code this key accepted. A code at or
    before it is refused even though the arithmetic says it is correct: a code
    is good for one sign-in, not for everyone who saw it over a shoulder in the
    same half minute.
    """
    code = normalise(code)
    if len(code) != DIGITS or not code.isdigit():
        return None

    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if after_step is not None and candidate <= after_step:
            continue
        if hmac.compare_digest(_code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret, *, account, issuer):
    """The otpauth:// address the QR code carries."""
    label = quote(f"{issuer}:{account}", safe="@:")
    query = urlencode({
        "secret": secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": DIGITS,
        "period": STEP_SECONDS,
    })
    return f"otpauth://totp/{label}?{query}"


def qr_svg(uri):
    """The provisioning address as an inline SVG QR code."""
    import segno

    return segno.make(uri, error="m").svg_inline(
        scale=5, border=2, dark="#0f172a", light="#ffffff", omitsize=True,
    )


def group(secret):
    """The key in fours, for typing it in by hand."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
