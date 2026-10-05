"""
Reading certificates and deciding whether they are PNPKI certificates.

"PNPKI" here means one thing only: the certificate chains, by signature, to a
DICT PNPKI root CA certificate installed on this server (ESIRA_PNPKI_TRUST_ROOTS).
Its issuer's name saying "PNPKI" is not evidence of anything - anyone can
write that into a self-made certificate.
"""

import asyncio
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from django.conf import settings

from .base import CredentialError

logger = logging.getLogger("lgmed.esira")


class CertificateRejected(ValueError):
    """The file is not a usable certificate. The message says why."""


@dataclass(frozen=True)
class ChainResult:
    trusted: bool
    note: str


# -- reading --------------------------------------------------------------


def load_certificate(data):
    """A certificate from PEM or DER bytes (.cer, .crt, .pem)."""
    data = bytes(data or b"")
    try:
        if b"-----BEGIN CERTIFICATE-----" in data:
            return x509.load_pem_x509_certificate(data)
        return x509.load_der_x509_certificate(data)
    except ValueError:
        raise CertificateRejected(
            "The file is not an X.509 certificate. Upload the .cer, .crt or "
            ".pem file, or your .p12 / .pfx certificate file with its passphrase."
        )


def open_pkcs12(data, passphrase):
    """
    Open a PKCS#12 file. Returns (private_key, certificate, other_certs).

    The caller owns the key and must drop it as soon as it is done.
    """
    try:
        key, certificate, others = pkcs12.load_key_and_certificates(
            bytes(data or b""), (passphrase or "").encode("utf-8") or None,
        )
    except (ValueError, TypeError):
        raise CredentialError(
            "The certificate file could not be opened. Check that it is your "
            ".p12 or .pfx file and that the passphrase is correct."
        )
    if certificate is None or key is None:
        raise CredentialError(
            "The certificate file does not contain both a certificate and its "
            "private key."
        )
    return key, certificate, list(others or [])


def certificate_from_pkcs12(data, passphrase):
    """The public certificate inside a PKCS#12 file. The key is discarded."""
    key, certificate, others = open_pkcs12(data, passphrase)
    del key
    return certificate, others


def to_pem(certificate):
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def fingerprint(certificate):
    return certificate.fingerprint(hashes.SHA256()).hex()


def _name_attr(name, oid):
    values = name.get_attributes_for_oid(oid)
    return values[0].value if values else ""


def _aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value


def describe(certificate):
    """The fields e-SIRA records about a certificate."""
    subject = certificate.subject
    email = _name_attr(subject, NameOID.EMAIL_ADDRESS)
    if not email:
        try:
            san = certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            emails = san.get_values_for_type(x509.RFC822Name)
            email = emails[0] if emails else ""
        except x509.ExtensionNotFound:
            email = ""
    return {
        "subject": subject.rfc4514_string()[:500],
        "subject_common_name": _name_attr(subject, NameOID.COMMON_NAME)[:255],
        "subject_email": (email or "")[:255],
        "issuer": certificate.issuer.rfc4514_string()[:500],
        "serial_number": format(certificate.serial_number, "X")[:80],
        "fingerprint_sha256": fingerprint(certificate),
        "not_before": _aware(certificate.not_valid_before_utc),
        "not_after": _aware(certificate.not_valid_after_utc),
    }


def permits_signing(certificate):
    """
    Whether the certificate's key usage allows document signatures.

    A certificate issued for encryption or TLS only must not sign documents,
    whatever chain it has.
    """
    try:
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        return True  # no restriction declared
    return bool(usage.digital_signature or usage.content_commitment)


# -- trust ------------------------------------------------------------------


_ROOT_CACHE = {}


def trust_roots():
    """
    The DICT PNPKI CA certificates installed on this server, as asn1crypto
    certificates. Read once per distinct setting value.
    """
    from asn1crypto import x509 as asn1_x509

    paths = tuple(getattr(settings, "ESIRA_PNPKI_TRUST_ROOTS", ()) or ())
    if paths in _ROOT_CACHE:
        return _ROOT_CACHE[paths]
    roots = []
    for raw in paths:
        path = Path(raw)
        try:
            data = path.read_bytes()
            certificate = load_certificate(data)
            roots.append(
                asn1_x509.Certificate.load(
                    certificate.public_bytes(serialization.Encoding.DER)
                )
            )
        except (OSError, CertificateRejected):
            logger.error("e-SIRA: PNPKI trust root %s could not be loaded", path)
    _ROOT_CACHE[paths] = roots
    return roots


def untrusted_allowed():
    return bool(settings.DEBUG and getattr(settings, "ESIRA_ALLOW_UNTRUSTED_CERTIFICATES", False))


def check_chain(certificate, intermediates=()):
    """
    Validate the certificate's path to a PNPKI root, now.

    Revocation is checked against the PNPKI OCSP/CRL services only when
    ESIRA_CHECK_REVOCATION is on - the office network may not reach them -
    and then in hard-fail mode, so an unreachable responder refuses rather
    than waves through.
    """
    from asn1crypto import x509 as asn1_x509
    from pyhanko_certvalidator import CertificateValidator, ValidationContext
    from pyhanko_certvalidator.errors import PathBuildingError, PathValidationError

    roots = trust_roots()
    if not roots:
        return ChainResult(
            False,
            "No DICT PNPKI root certificates are installed on this server, so "
            "no certificate can be confirmed as PNPKI-issued.",
        )

    def asn1(cert):
        return asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))

    check_revocation = getattr(settings, "ESIRA_CHECK_REVOCATION", False)
    context = ValidationContext(
        trust_roots=roots,
        allow_fetching=check_revocation,
        revocation_mode="hard-fail" if check_revocation else "soft-fail",
    )
    validator = CertificateValidator(
        asn1(certificate),
        intermediate_certs=[asn1(c) for c in intermediates],
        validation_context=context,
    )
    try:
        asyncio.run(validator.async_validate_usage(set()))
    except PathBuildingError:
        return ChainResult(
            False, "The certificate does not chain to an installed DICT PNPKI root.",
        )
    except PathValidationError as exc:
        return ChainResult(False, f"The certificate chain is not valid: {exc}"[:500])
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("e-SIRA: certificate validation failed unexpectedly")
        return ChainResult(False, f"The certificate could not be validated ({exc.__class__.__name__}).")
    return ChainResult(True, "Chains to an installed DICT PNPKI root certificate.")
