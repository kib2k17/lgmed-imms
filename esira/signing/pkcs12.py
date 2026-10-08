"""
Signing with a PNPKI certificate file (PKCS#12, .p12 / .pfx).

DICT issues PNPKI individual certificates to government employees as a
password-protected PKCS#12 file. The file and passphrase come either from the
signer's encrypted store (esira.signing.vault) or from the signing dialog. The
key is opened in memory, used for the signatures on this one document, and
dropped; it is never written out in the clear.

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
from django.utils import timezone

from .base import OpenedCredential, SigningBackend, SigningError
from .certificates import open_pkcs12

# What the signature box shows. %(signer)s is the certificate holder's name,
# %(date)s the signing time in the office's time zone (see signing_date).
DESCRIPTION_TEXT = "Digitally signed by %(signer)s\nDate: %(date)s"
GRAPHIC_TEXT = "Digitally signed by\n%(signer)s\nDate: %(date)s"
# Share of the box the picture takes in the "graphic" style; the text has the rest.
GRAPHIC_SHARE = 0.42


def signing_date(moment=None):
    """e.g. 2026.10.08 15:04:32 PST - local time, with the office's zone label."""
    moment = timezone.localtime(moment)
    label = getattr(settings, "ESIRA_TIME_ZONE_LABEL", "") or moment.strftime("%Z")
    return f"{moment:%Y.%m.%d %H:%M:%S} {label}".strip()


def _font():
    from pyhanko.pdf_utils.font.basic import SimpleFontEngineFactory
    from pyhanko.pdf_utils.text import TextBoxStyle

    return TextBoxStyle(font=SimpleFontEngineFactory("Helvetica", 0.5))


class Pkcs12Backend(SigningBackend):
    key = "pkcs12"
    label = "PNPKI certificate file (.p12 / .pfx)"
    collects_credentials = True
    instructions = (
        "Select the PNPKI certificate file DICT issued to you (.p12 or .pfx) "
        "and enter its passphrase, or keep them on file on the My Certificates "
        "page."
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

    @staticmethod
    def _picture(request):
        if request.appearance == "description" or not request.appearance_image:
            return None
        from PIL import Image
        from pyhanko.pdf_utils.images import PdfImage

        try:
            picture = Image.open(io.BytesIO(request.appearance_image))
            picture.load()
        except Exception as exc:
            raise SigningError(
                "Your signature image could not be read. Upload it again on "
                "the My Signature Style page."
            ) from exc
        return PdfImage(picture)

    @staticmethod
    def _style(appearance, picture, rect):
        """
        The box's appearance for one placement. Margins are in PDF points, so
        the side-by-side layout is worked out from this box's own width.
        """
        from pyhanko import stamp
        from pyhanko.pdf_utils.layout import (
            AxisAlignment,
            InnerScaling,
            Margins,
            SimpleBoxLayoutRule,
        )

        def layout(x_align, margins):
            return SimpleBoxLayoutRule(
                x_align=x_align,
                y_align=AxisAlignment.ALIGN_MID,
                margins=margins,
                inner_content_scaling=InnerScaling.SHRINK_TO_FIT,
            )

        if picture is None:
            appearance = "description"
        if appearance == "image":
            return stamp.StaticStampStyle(
                border_width=0,
                background=picture,
                background_opacity=1.0,
                background_layout=layout(AxisAlignment.ALIGN_MID, Margins.uniform(2)),
            )
        if appearance == "graphic":
            width = abs(rect[2] - rect[0])
            split = int(width * GRAPHIC_SHARE)
            return stamp.TextStampStyle(
                stamp_text=GRAPHIC_TEXT,
                text_box_style=_font(),
                border_width=0,
                background=picture,
                background_opacity=1.0,
                background_layout=layout(
                    AxisAlignment.ALIGN_MID,
                    Margins(left=2, right=max(width - split, 2), top=2, bottom=2),
                ),
                inner_content_layout=layout(
                    AxisAlignment.ALIGN_MIN,
                    Margins(left=split + 4, right=2, top=2, bottom=2),
                ),
            )
        return stamp.TextStampStyle(
            stamp_text=DESCRIPTION_TEXT,
            text_box_style=_font(),
            border_width=0,
            inner_content_layout=layout(AxisAlignment.ALIGN_MID, Margins.uniform(3)),
        )

    def _timestamper(self):
        url = getattr(settings, "ESIRA_TSA_URL", "")
        if not url:
            return None
        from pyhanko.sign.timestamps import HTTPTimeStamper

        return HTTPTimeStamper(url)

    def sign(self, opened, request):
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import fields, signers

        if opened is None or opened.handle is None:
            raise SigningError("No signing key is open.")
        if not request.placements:
            raise SigningError("There is no signature box to sign.")

        signer = self._signer(opened)
        timestamper = self._timestamper()
        picture = self._picture(request)

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
                    stamp_style=self._style(request.appearance, picture, placement.rect),
                    new_field_spec=fields.SigFieldSpec(
                        placement.field_name,
                        on_page=placement.page_index,
                        box=placement.rect,
                    ),
                )
                output = io.BytesIO()
                pdf_signer.sign_pdf(
                    writer, output=output,
                    appearance_text_params={"date": signing_date()},
                )
                data = output.getvalue()
            except SigningError:
                raise
            except Exception as exc:
                raise SigningError(
                    f"The signature on page {placement.page_index + 1} could not "
                    f"be applied ({exc.__class__.__name__})."
                ) from exc
        return data
