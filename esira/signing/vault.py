"""
Encryption for the certificate files and passphrases signers keep on file.

A signer may store their PNPKI .p12 / .pfx and its passphrase so they need not
present them every time they sign. Both are kept only as Fernet tokens
(AES-128-CBC with HMAC-SHA256), under a key that lives in the server's
environment and never in the database:

    ESIRA_CREDENTIAL_KEY   a Fernet key (python -c "from cryptography.fernet
                           import Fernet; print(Fernet.generate_key().decode())")

Without it the key is derived from DJANGO_SECRET_KEY, so a database copy alone
still opens nothing - but changing the secret key then makes every stored
credential unreadable, and signers must upload their files again. Set
ESIRA_CREDENTIAL_KEY in production so the two can change independently.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import CredentialError


def _fernet():
    configured = getattr(settings, "ESIRA_CREDENTIAL_KEY", "")
    if configured:
        try:
            return Fernet(configured.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            raise ImproperlyConfigured(
                "ESIRA_CREDENTIAL_KEY is not a valid Fernet key."
            )
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"lgmed-esira-credential-vault",
    ).derive(settings.SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def seal(data):
    """Encrypt bytes (or text) for storage."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _fernet().encrypt(bytes(data))


def unseal(token):
    """Decrypt a stored token back to bytes."""
    try:
        return _fernet().decrypt(bytes(token))
    except (InvalidToken, TypeError, ValueError):
        raise CredentialError(
            "Your stored certificate could not be decrypted on this server. "
            "Upload your .p12 file again on the My Certificates page."
        )
