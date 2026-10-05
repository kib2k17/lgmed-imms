"""
Signing with a PNPKI certificate file (PKCS#12, .p12 / .pfx).

DICT issues PNPKI individual certificates to government employees as a
password-protected PKCS#12 file. The signer selects that file and types its
passphrase in the signing dialog; both travel over the (TLS) connection with
the signing request, are opened in memory, used for the signatures on this one
document, and dropped. Neither is written to disk, the database or a log.

Each signature box becomes its own PAdES signature field (ETSI.CAdES.detached,
SHA-256), applied as an incremental update so that every earlier signature on
the document - this signer's and everyone else's - stays intact and
verifiable. A visible appearance is drawn inside the box by the signing
operation itself, so what a reader sees on the page is the signature widget,
not a picture laid over the page.
"""

import io

from cryptography.hazmat.primitives import serialization
from django.conf import settings

from .base import OpenedCredential, SigningBackend, SigningError
from .certificates import open_pkcs12

STAMP_TEXT = "Digitally signed by\n%(signer)s\n%(ts)s"


class Pkcs12Backend(SigningBackend):
    key = "pkcs12"
    label = "PNPKI certificate file (.p12 / .pfx)"
    collects_credentials = True
    instructions = (
        "Select the PNPKI certificate file DICT issued to you (.p12 or .pfx) "
        "and enter its passphrase. The file and passphrase are used for this "
        "signature only and are not stored."
    )

    def open(self, credentials):
        data = credentials.get("pkcs12") or b""
        passphrase = credentials.get("passphrase") or ""
        key, certificate, others = open_pkcs12(data, passphrase)
        return OpenedCredential(
            certificate=certificate, chain=others, handle=key,
        )

    def _signer(self, opened):
        from asn1crypto import keys as asn1_keys
        from asn1crypto import x509 as asn1_x509
        from pyhanko.sign.signers import SimpleSigner
        from pyhanko_certvalidator.registry import SimpleCertificateStore

        def asn1(cert):
            return asn1_x509.Certificate.load(
                cert.public_bytes(serialization.Encoding.DER)
            )

        key_info = asn1_keys.PrivateKeyInfo.load(
            opened.handle.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return SimpleSigner(
            signing_cert=asn1(opened.certificate),
            signing_key=key_info,
            cert_registry=SimpleCertificateStore.from_certs(
                [asn1(c) for c in opened.chain]
            ),
        )

    def _timestamper(self):
        url = getattr(settings, "ESIRA_TSA_URL", "")
        if not url:
            return None
        from pyhanko.sign.timestamps import HTTPTimeStamper

        return HTTPTimeStamper(url)

    def sign(self, opened, request):
        from pyhanko import stamp
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.pdf_utils.layout import (
            AxisAlignment,
            InnerScaling,
            Margins,
            SimpleBoxLayoutRule,
        )
        from pyhanko.sign import fields, signers

        if opened is None or opened.handle is None:
            raise SigningError("No signing key is open.")
        if not request.placements:
            raise SigningError("There is no signature box to sign.")

        signer = self._signer(opened)
        timestamper = self._timestamper()
        style = stamp.TextStampStyle(
            stamp_text=STAMP_TEXT,
            border_width=1,
            timestamp_format="%d %b %Y %H:%M %Z",
            inner_content_layout=SimpleBoxLayoutRule(
                x_align=AxisAlignment.ALIGN_MID,
                y_align=AxisAlignment.ALIGN_MID,
                margins=Margins.uniform(3),
                inner_content_scaling=InnerScaling.SHRINK_TO_FIT,
            ),
        )

        data = request.pdf_bytes
        for placement in request.placements:
            try:
                writer = IncrementalPdfFileWriter(io.BytesIO(data), strict=False)
                meta = signers.PdfSignatureMetadata(
                    field_name=placement.field_name,
                    md_algorithm="sha256",
                    reason=request.reason or None,
                    location=request.location or None,
                    contact_info=request.contact_info or None,
                    subfilter=fields.SigSeedSubFilter.PADES,
                )
                pdf_signer = signers.PdfSigner(
                    meta,
                    signer,
                    timestamper=timestamper,
                    stamp_style=style,
                    new_field_spec=fields.SigFieldSpec(
                        placement.field_name,
                        on_page=placement.page_index,
                        box=placement.rect,
                    ),
                )
                output = io.BytesIO()
                pdf_signer.sign_pdf(writer, output=output)
                data = output.getvalue()
            except SigningError:
                raise
            except Exception as exc:
                raise SigningError(
                    f"The signature on page {placement.page_index + 1} could not "
                    f"be applied ({exc.__class__.__name__})."
                ) from exc
        return data
