"""
Verifying the signatures a PDF actually carries.

This reads the signatures out of the file itself and checks them
cryptographically - it does not take e-SIRA's own records on trust. A signed
document downloaded from e-SIRA and opened in Adobe Acrobat or the DICT PNPKI
verifier should reach the same conclusions.
"""

import io
from dataclasses import dataclass

from .signing.certificates import trust_roots


@dataclass
class SignatureReport:
    field_name: str
    signer: str
    issuer: str
    serial: str
    signing_time: object
    intact: bool
    valid: bool
    trusted: bool
    covers_document: bool
    modification: str
    summary: str
    esira_signature: object = None

    @property
    def tone(self):
        if not (self.intact and self.valid):
            return "failed"
        return "verified" if self.trusted else "pending"

    @property
    def verdict(self):
        if not self.intact:
            return "Altered after signing"
        if not self.valid:
            return "Signature invalid"
        if not self.trusted:
            return "Valid - certificate not PNPKI-verified"
        return "Valid PNPKI signature"


def verify_pdf(data, esira_signatures=()):
    """A report for each signature embedded in `data`, in signing order."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    roots = trust_roots()
    context = ValidationContext(trust_roots=roots) if roots else None
    known = {}
    for signature in esira_signatures:
        for name in signature.field_names or []:
            known[name] = signature

    reader = PdfFileReader(io.BytesIO(data), strict=False)
    reports = []
    for embedded in reader.embedded_signatures:
        cert = embedded.signer_cert
        try:
            status = validate_pdf_signature(embedded, context)
            intact, valid = status.intact, status.valid
            trusted = bool(status.trusted) and context is not None
            modification = getattr(status.modification_level, "name", "")
            covers = status.coverage is not None and status.coverage.name in (
                "ENTIRE_FILE", "ENTIRE_REVISION",
            )
            summary = status.summary()
            signing_time = status.signer_reported_dt
        except Exception as exc:  # a malformed signature must not hide the rest
            intact = valid = trusted = covers = False
            modification, summary, signing_time = "", f"Could not be checked ({exc.__class__.__name__})", None
        reports.append(SignatureReport(
            field_name=embedded.field_name,
            signer=cert.subject.human_friendly if cert else "Unknown",
            issuer=cert.issuer.human_friendly if cert else "",
            serial=format(cert.serial_number, "X") if cert else "",
            signing_time=signing_time,
            intact=intact,
            valid=valid,
            trusted=trusted,
            covers_document=covers,
            modification=modification.replace("_", " ").title(),
            summary=summary,
            esira_signature=known.get(embedded.field_name),
        ))
    return reports
