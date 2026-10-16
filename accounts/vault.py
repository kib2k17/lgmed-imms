"""
Encryption for the two-step verification secrets.

An authenticator's secret is what the server computes each six-digit code
from, so anyone holding it can produce valid codes. Stored in plain text, a
copy of the database - a leaked backup - reduced two-step verification to the
password alone (SECURITY_AUDIT.md, M-06). It is kept as a Fernet token
(AES-128-CBC with HMAC-SHA256) under a key that lives in the server's
environment, never in the database:

    LGMED_MFA_KEY   a Fernet key (python -c "from cryptography.fernet
                    import Fernet; print(Fernet.generate_key().decode())")

Without it the key is derived from DJANGO_SECRET_KEY - the same pattern as
esira/signing/vault.py, and the same trade-off: a database copy alone still
opens nothing, but changing the secret key then makes every enrolled
authenticator unreadable, and its holders must be reset and enrol again.
(Recovery codes are keyed on SECRET_KEY already.) Set LGMED_MFA_KEY in
production so the two can change independently.
"""

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

# Every Fernet token starts with these characters (version byte 0x80, then the
# timestamp's high bytes). A base32 authenticator secret never can - it has no
# lower-case letters - so the two are told apart without a marker column.
TOKEN_PREFIX = "gAAAAA"


def _fernet():
    configured = getattr(settings, "LGMED_MFA_KEY", "")
    if configured:
        try:
            return Fernet(configured.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            raise ImproperlyConfigured("LGMED_MFA_KEY is not a valid Fernet key.")
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"lgmed-mfa-secret",
    ).derive(settings.SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def is_sealed(value):
    return bool(value) and value.startswith(TOKEN_PREFIX)


def seal(secret):
    """Encrypt an authenticator secret for storage. Already sealed stays as is."""
    if not secret or is_sealed(secret):
        return secret
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def unseal(stored):
    """
    The authenticator secret from its stored form, or None when it cannot be
    decrypted on this server (the key changed). A value still in plain text -
    one written before encryption - is returned as it is.
    """
    if not stored or not is_sealed(stored):
        return stored or None
    try:
        return _fernet().decrypt(stored.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeError):
        logger.error(
            "A two-step verification secret could not be decrypted: LGMED_MFA_KEY "
            "or DJANGO_SECRET_KEY has changed. Reset that account's two-step "
            "verification so its holder can enrol again."
        )
        return None
