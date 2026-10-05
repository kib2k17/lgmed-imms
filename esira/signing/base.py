"""
The contract every signing mechanism meets.

Signing happens in two steps, and the workflow runs its checks between them:

    opened = backend.open(credentials)      # proves possession of a key and
                                            # says which certificate it is
    ... the workflow checks that certificate is this user's, verified,
        in date and chained to PNPKI ...
    signed_pdf = backend.sign(opened, request)

So no key is ever used to sign until the system has decided that key is
allowed to sign this document, and a backend never makes that decision itself.

A backend produces a real PAdES signature or it raises. There is no path that
returns a document marked "signed" without a private-key operation behind it.
"""

from dataclasses import dataclass, field


class SigningError(Exception):
    """Signing could not go ahead. The message is safe to show the user."""


class SigningBackendUnavailable(SigningError):
    """The configured mechanism is not connected on this server."""


class CredentialError(SigningError):
    """The certificate file or passphrase could not be opened."""


@dataclass(frozen=True)
class Placement:
    """One visible signature: which page (0-based) and where, in PDF units."""

    page_index: int
    rect: tuple  # (x1, y1, x2, y2) in the page's user space
    field_name: str


@dataclass(frozen=True)
class SignatureRequest:
    pdf_bytes: bytes
    placements: tuple
    reason: str = ""
    location: str = ""
    contact_info: str = ""


@dataclass
class OpenedCredential:
    """
    A credential that has proved it holds a private key.

    `certificate` is a `cryptography` x509 certificate; `chain` any further
    certificates the credential carried. `handle` belongs to the backend.
    """

    certificate: object
    chain: list = field(default_factory=list)
    handle: object = None


class SigningBackend:
    key = ""
    label = ""
    # Whether the signing form asks the signer for a certificate file and
    # passphrase. An agent-based backend gets them from the signer's own
    # computer instead.
    collects_credentials = True
    # Shown on the signing page so the signer knows what will be asked of them.
    instructions = ""

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    def open(self, credentials):  # pragma: no cover - interface
        raise NotImplementedError

    def sign(self, opened, request):  # pragma: no cover - interface
        raise NotImplementedError

    def close(self, opened):
        """Drop any reference to key material as soon as signing is over."""
        if opened is not None:
            opened.handle = None
