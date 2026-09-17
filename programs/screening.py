"""
Automated screening of uploaded documents.

What this module is
-------------------

A *screening*. It reads what it can of a file and reports what looks like it
might be personal, confidential or otherwise not for release. It does not
decide anything. Section 6 of the module brief states the rule this whole file
is built around, and it is worth restating where the code lives:

    A clean result means the scanner found nothing.
    It does not mean there is nothing there.

So `classify()` below has no branch that returns "safe, publish it". The best
result a file can get is LOW - "no obvious sensitive information detected" -
and a LOW file still goes to a human reviewer before anything happens to it.
The same asymmetry runs through the extraction code: whenever the scanner
cannot read a file properly, that fact is itself recorded as a finding and the
result is raised to REVIEW REQUIRED. A document the scanner could not open is
the *last* document that should be waved through.

What it can read
----------------

PDF, the Office XML formats (docx / xlsx / pptx), and plain text with the
standard library alone, so the screening works on a bare Django install. Two
optional libraries widen it if the office installs them:

    pypdf        better PDF text extraction, including awkward encodings
    pytesseract  optical character recognition for scanned pages and images

Their absence is not a silent degradation: the scanner says so in its notes and
in a finding, and the file is marked as needing review rather than passed.
"""

import io
import logging
import re
import zipfile
import zlib
from dataclasses import dataclass, field

from django.utils import timezone

logger = logging.getLogger("lgmed.programs.screening")

# Severities a single finding can carry. They are not the same thing as the
# document's risk level: the level is computed from the findings by
# `classify()`.
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

# Keep the stored JSON small and the review screen readable. A file with 400
# phone numbers in it does not need 400 examples to make its point.
MAX_EVIDENCE_PER_FINDING = 5
MAX_SEGMENT_CHARS = 400_000


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    """A readable piece of the document, and where in it that piece was."""

    label: str      # "page 3", "Sheet: Attendance", "slide 2", "properties"
    text: str


@dataclass
class Extraction:
    """Everything the scanner managed to get out of one file."""

    segments: list = field(default_factory=list)
    method: str = ""
    complete: bool = False      # the scanner believes it read the whole file
    notes: list = field(default_factory=list)

    @property
    def text(self):
        return "\n".join(segment.text for segment in self.segments)

    @property
    def has_text(self):
        return bool(self.text.strip())


def _clean(text):
    """Normalise whitespace so patterns are not defeated by layout."""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_SEGMENT_CHARS]


# -- plain text --------------------------------------------------------------


def _extract_text_file(data):
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return Extraction(
                segments=[Segment("document", _clean(data.decode(encoding)))],
                method="plain text",
                complete=True,
            )
        except UnicodeDecodeError:
            continue
    return Extraction(method="plain text", complete=False,
                      notes=["The file's character encoding could not be determined."])


# -- PDF ---------------------------------------------------------------------

_PDF_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>", re.S)
_PDF_SHOW = re.compile(rb"(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>)\s*(?:Tj|TJ|'|\")")
_PDF_INFO = re.compile(
    rb"/(Author|Title|Subject|Keywords|Creator|Producer)\s*(\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>)"
)


def _pdf_unescape(token):
    """Turn one PDF string token into text."""
    if token.startswith(b"<"):
        hex_digits = re.sub(rb"[^0-9A-Fa-f]", b"", token[1:-1])
        if len(hex_digits) % 2:
            hex_digits += b"0"
        try:
            raw = bytes.fromhex(hex_digits.decode("ascii"))
        except ValueError:
            return ""
        # Hex strings are usually UTF-16BE when they are not font-subset codes.
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return raw.decode("latin-1", "ignore")

    body = token[1:-1]
    body = re.sub(rb"\\([nrtbf()\\])", lambda m: {
        b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"", b"f": b"",
        b"(": b"(", b")": b")", b"\\": b"\\",
    }[m.group(1)], body)
    body = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), body)
    return body.decode("latin-1", "ignore")


def _extract_pdf_with_pypdf(data):
    """Preferred route: pypdf understands font encodings this module does not."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return Extraction(
                    method="pypdf", complete=False,
                    notes=["The PDF is password-protected and could not be read."],
                )
        segments = []
        meta = reader.metadata or {}
        properties = " ".join(
            f"{key.lstrip('/')}: {value}" for key, value in meta.items() if value
        )
        if properties:
            segments.append(Segment("document properties", _clean(properties)))
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                segments.append(Segment(f"page {number}", _clean(text)))
        pages_with_text = sum(1 for s in segments if s.label.startswith("page"))
        notes = []
        complete = True
        if pages_with_text < len(reader.pages):
            complete = False
            notes.append(
                f"{len(reader.pages) - pages_with_text} of {len(reader.pages)} "
                "page(s) contain no machine-readable text - they are most "
                "likely scanned images."
            )
        return Extraction(segments=segments, method="pypdf",
                          complete=complete, notes=notes)
    except Exception as exc:  # a malformed PDF must not break the upload
        logger.warning("pypdf failed to read a PDF: %s", exc)
        return None


def _extract_pdf_builtin(data):
    """
    Fallback PDF reader built on the standard library.

    Inflates the content streams and pulls out the text-showing operators. It
    is good enough to catch a "CONFIDENTIAL" banner or a column of ID numbers,
    which is what a screening is for, and it is honest about the rest: a PDF
    whose fonts use subset encodings comes back as nonsense, so the extraction
    is marked incomplete and the reviewer is told to read the file themselves.
    """
    notes = []
    if b"/Encrypt" in data:
        return Extraction(
            method="built-in PDF reader", complete=False,
            notes=["The PDF appears to be encrypted and could not be read."],
        )

    segments = []
    properties = []
    for match in _PDF_INFO.finditer(data):
        value = _pdf_unescape(match.group(2)).strip()
        if value:
            properties.append(f"{match.group(1).decode()}: {value}")
    if properties:
        segments.append(Segment("document properties", _clean("\n".join(properties))))

    pieces = []
    streams = 0
    unreadable = 0
    for match in re.finditer(rb"stream\r?\n?(.*?)endstream", data, re.S):
        streams += 1
        blob = match.group(1)
        try:
            blob = zlib.decompress(blob)
        except zlib.error:
            try:
                # A truncated or slightly malformed Flate stream; take what
                # inflates rather than throwing the whole page away.
                blob = zlib.decompressobj().decompress(blob)
            except zlib.error:
                # Not compressed at all. Plenty of PDFs - anything produced by
                # a simple generator, and most government forms - carry their
                # content streams as plain text, so the operators are already
                # right there. Only a stream that is neither inflatable nor
                # legible is genuinely unreadable.
                if not _PDF_SHOW.search(blob):
                    unreadable += 1
                    continue
        if b"Tj" not in blob and b"TJ" not in blob:
            continue
        shown = [_pdf_unescape(m.group(1)) for m in _PDF_SHOW.finditer(blob)]
        if shown:
            pieces.append(" ".join(shown))

    body = _clean("\n".join(pieces))
    if body.strip():
        segments.append(Segment("document body", body))

    # Font-subset encodings produce text with almost no spaces or vowels. When
    # that is what came out, say so rather than pretending the file was read.
    legible = _looks_like_prose(body)
    if not legible and body.strip():
        notes.append(
            "The PDF's text could only be read partially; its fonts use an "
            "encoding this scanner cannot map. Read the file yourself before "
            "deciding."
        )
    if unreadable:
        notes.append(
            f"{unreadable} of {streams} internal stream(s) could not be "
            "decompressed - the file may contain images or scanned pages."
        )
    if not body.strip():
        notes.append(
            "No machine-readable text was found. The PDF is most likely a "
            "scan, and its contents have not been screened."
        )

    return Extraction(
        segments=segments,
        method="built-in PDF reader",
        complete=bool(body.strip()) and legible and not unreadable,
        notes=notes,
    )


def _looks_like_prose(text):
    """A cheap check that extracted text is words rather than font codes."""
    sample = text[:4000]
    if len(sample) < 40:
        return False
    letters = sum(1 for ch in sample if ch.isalpha())
    spaces = sample.count(" ")
    return letters > len(sample) * 0.4 and spaces > len(sample) * 0.08


def _extract_pdf(data):
    result = _extract_pdf_with_pypdf(data)
    if result is not None and result.has_text:
        return result
    builtin = _extract_pdf_builtin(data)
    if result is not None and not result.has_text:
        builtin.notes = list(dict.fromkeys(result.notes + builtin.notes))
    return builtin


# -- the Office XML formats --------------------------------------------------

_XML_TAG = re.compile(r"<[^>]+>")


def _xml_text(raw, paragraph_tags=()):
    """Strip an Office XML part down to its words."""
    text = raw.decode("utf-8", "ignore")
    for tag in paragraph_tags:
        text = text.replace(f"</{tag}>", f"</{tag}>\n")
    text = _XML_TAG.sub(" ", text)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&apos;", "'"), ("&#8217;", "'")):
        text = text.replace(entity, char)
    return _clean(text)


def _extract_office_xml(data, extension):
    """
    Read docx / xlsx / pptx.

    All three are ZIP archives of XML, so the standard library is enough: the
    parts are located by name and reduced to their text. Document properties
    are read too - `docProps/core.xml` carries the author and the last person
    to save the file, which is personal information the office rarely
    remembers it is shipping.
    """
    segments = []
    notes = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return Extraction(
            method="Office XML reader", complete=False,
            notes=["The file is not a readable Office document."],
        )

    names = set(archive.namelist())

    for part, label in (("docProps/core.xml", "document properties"),
                        ("docProps/app.xml", "document properties")):
        if part in names:
            text = _xml_text(archive.read(part))
            if text.strip():
                segments.append(Segment(label, text))

    if extension == "docx":
        for part in ("word/document.xml", "word/footnotes.xml",
                     "word/endnotes.xml", "word/comments.xml"):
            if part in names:
                text = _xml_text(archive.read(part), paragraph_tags=("w:p",))
                if text.strip():
                    segments.append(Segment(part.rsplit("/", 1)[-1][:-4], text))
        for part in sorted(n for n in names if re.match(r"word/(header|footer)\d+\.xml", n)):
            text = _xml_text(archive.read(part), paragraph_tags=("w:p",))
            if text.strip():
                segments.append(Segment(part.rsplit("/", 1)[-1][:-4], text))

    elif extension == "xlsx":
        # Sheet names live in the workbook part; the cell text lives in the
        # shared string table. Reporting a finding as "Sheet: Attendance"
        # rather than "somewhere in the file" is what makes the review
        # screen useful.
        sheet_names = []
        if "xl/workbook.xml" in names:
            sheet_names = re.findall(
                r'<sheet[^>]*name="([^"]+)"', archive.read("xl/workbook.xml").decode("utf-8", "ignore")
            )
        if "xl/sharedStrings.xml" in names:
            text = _xml_text(archive.read("xl/sharedStrings.xml"), paragraph_tags=("si",))
            if text.strip():
                segments.append(Segment("cell contents", text))
        for index, part in enumerate(
            sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml", n))
        ):
            label = sheet_names[index] if index < len(sheet_names) else f"sheet {index + 1}"
            text = _xml_text(archive.read(part), paragraph_tags=("row",))
            if text.strip():
                segments.append(Segment(f"sheet: {label}", text))

    elif extension == "pptx":
        slides = sorted(
            (n for n in names if re.match(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        for part in slides:
            number = re.search(r"(\d+)", part).group(1)
            text = _xml_text(archive.read(part), paragraph_tags=("a:p",))
            if text.strip():
                segments.append(Segment(f"slide {number}", text))
        for part in sorted(n for n in names if n.startswith("ppt/notesSlides/")):
            text = _xml_text(archive.read(part), paragraph_tags=("a:p",))
            if text.strip():
                segments.append(Segment("speaker notes", text))

    # Embedded pictures are not read. Say so, because a pasted screenshot of a
    # payroll is a real way for a spreadsheet to carry data the text does not.
    images = [n for n in names if re.match(r".*/media/.*\.(png|jpe?g|emf|wmf)$", n, re.I)]
    if images:
        notes.append(
            f"The file embeds {len(images)} image(s). Images are not read "
            "unless optical character recognition is available, so anything "
            "written inside them has not been screened."
        )

    return Extraction(
        segments=segments,
        method="Office XML reader",
        complete=bool(segments) and not images,
        notes=notes,
    )


# -- the legacy binary Office formats ---------------------------------------


def _extract_legacy_office(data):
    """
    .doc / .xls / .ppt - the pre-2007 binary formats.

    These are OLE compound files and there is no standard-library reader for
    them. What this does instead is pull printable runs out of the raw bytes,
    in both Latin-1 and UTF-16, which reliably catches banner words like
    CONFIDENTIAL and strings of digits, and reliably produces rubbish around
    them. It is marked incomplete for that reason: a legacy Office file always
    reaches the reviewer as REVIEW REQUIRED.
    """
    runs = []
    for match in re.finditer(rb"(?:[\x20-\x7e]\x00){6,}", data):
        runs.append(match.group().decode("utf-16-le", "ignore"))
    for match in re.finditer(rb"[\x20-\x7e]{8,}", data):
        runs.append(match.group().decode("latin-1", "ignore"))

    text = _clean("\n".join(runs))
    return Extraction(
        segments=[Segment("document body", text)] if text.strip() else [],
        method="legacy Office byte scan",
        complete=False,
        notes=[
            "This is a pre-2007 Office file. Only a partial, approximate read "
            "of its text was possible, so the screening below is not a full "
            "one. Save the file as PDF or a modern Office format, or read it "
            "yourself before releasing it."
        ],
    )


# -- images ------------------------------------------------------------------


def _extract_image(data):
    """
    Optical character recognition, if the office has installed it.

    Without it there is nothing to screen: an image of a payroll is, to this
    scanner, an opaque blob. That is reported as a finding rather than passed
    over, because a photograph is exactly the kind of upload that carries a
    whiteboard of names or a signed attendance sheet.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return Extraction(
            method="none", complete=False,
            notes=[
                "This is an image, and optical character recognition is not "
                "installed on this server, so any text inside it has not been "
                "screened. Open the image and look at it before releasing it."
            ],
        )

    try:
        text = pytesseract.image_to_string(Image.open(io.BytesIO(data)))
    except Exception as exc:
        logger.warning("OCR failed: %s", exc)
        return Extraction(
            method="optical character recognition", complete=False,
            notes=[f"Optical character recognition failed to read the image ({exc})."],
        )

    return Extraction(
        segments=[Segment("image text", _clean(text))] if text.strip() else [],
        method="optical character recognition",
        # OCR is approximate by nature; never claim a complete read.
        complete=False,
        notes=[
            "The text in this image was read by optical character "
            "recognition, which is approximate. Look at the image as well."
        ],
    )


EXTRACTORS = {
    "pdf": _extract_pdf,
    "docx": lambda data: _extract_office_xml(data, "docx"),
    "xlsx": lambda data: _extract_office_xml(data, "xlsx"),
    "pptx": lambda data: _extract_office_xml(data, "pptx"),
    "doc": _extract_legacy_office,
    "xls": _extract_legacy_office,
    "ppt": _extract_legacy_office,
    "jpg": _extract_image,
    "jpeg": _extract_image,
    "png": _extract_image,
    "txt": _extract_text_file,
    "csv": _extract_text_file,
}


def extract(data, extension):
    """Read what can be read of one file. Never raises."""
    handler = EXTRACTORS.get(extension)
    if handler is None:
        return Extraction(
            method="none", complete=False,
            notes=[f"No reader is available for .{extension} files."],
        )
    try:
        return handler(data)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Extraction failed for a .%s file", extension)
        return Extraction(
            method="none", complete=False,
            notes=[f"The file could not be read ({exc.__class__.__name__})."],
        )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
#
# Each rule is a pattern plus what to say about it. The severities are chosen
# from the reviewer's point of view rather than the regex's: HIGH means "this
# file must not go out until somebody has read it and said why it is safe",
# MEDIUM means "look at this", LOW means "you should know this is in there".


@dataclass
class Rule:
    code: str
    label: str
    category: str
    severity: str
    pattern: re.Pattern
    advice: str = ""
    # A match is only reported when one of these words also appears nearby.
    # Used where the pattern alone is too generic to stand on its own.
    context: tuple = ()
    mask: bool = True


def _p(expression, flags=re.I):
    return re.compile(expression, flags)


PERSONAL = "personal"
CONFIDENTIAL = "confidential"
CREDENTIAL = "credential"
INTERNAL = "internal"
COVERAGE = "coverage"


RULES = [
    # -- government identification numbers ------------------------------
    Rule("tin", "Taxpayer Identification Number (TIN)", PERSONAL, HIGH,
         _p(r"\b\d{3}[-\s]\d{3}[-\s]\d{3}(?:[-\s]\d{3,5})?\b"),
         "A TIN identifies a named taxpayer and must not be published."),
    Rule("sss", "SSS number", PERSONAL, HIGH,
         _p(r"\b\d{2}[-\s]\d{7}[-\s]\d\b"),
         "An SSS number must not be published."),
    Rule("philhealth", "PhilHealth number", PERSONAL, HIGH,
         _p(r"\b\d{2}[-\s]\d{9}[-\s]\d\b"),
         "A PhilHealth number must not be published."),
    Rule("pagibig", "Pag-IBIG MID number", PERSONAL, HIGH,
         _p(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}\b"),
         "A Pag-IBIG MID number must not be published."),
    Rule("gsis", "GSIS / BP number", PERSONAL, HIGH,
         _p(r"\b(?:gsis|bp)\s*(?:no\.?|number|#)?\s*[:\-]?\s*\d[\d\s-]{7,15}\b"),
         "A GSIS business partner number must not be published."),
    Rule("id_labelled", "Government ID number (labelled)", PERSONAL, HIGH,
         _p(r"\b(?:tin|sss|gsis|philhealth|pag-?ibig|hdmf|prc|umid|passport|"
            r"driver'?s?\s+licen[cs]e|voter'?s?\s+id)\b[^\n]{0,20}?"
            r"(?:no\.?|number|#|id)\s*[:\-]?\s*[\w-]{5,}"),
         "A labelled government identification number was found."),

    # -- money -----------------------------------------------------------
    Rule("bank_account", "Bank or account number", PERSONAL, HIGH,
         _p(r"\b(?:account|acct|a/c|savings|current|atm|lbp|landbank|dbp|bpi|"
            r"metrobank)\b[^\n]{0,25}?(?:no\.?|number|#)\s*[:\-]?\s*[\d-]{6,}"),
         "Account details must not be published."),
    Rule("card_number", "Payment card number", PERSONAL, HIGH,
         _p(r"\b(?:\d{4}[-\s]){3}\d{4}\b"),
         "A 16-digit number in card format was found."),

    # -- credentials and internal system information ----------------------
    Rule("password", "Password or credential", CREDENTIAL, HIGH,
         _p(r"\b(?:password|passwd|pwd|passphrase|credentials?)\b\s*[:=]\s*\S{3,}"),
         "Credentials must never leave the office, published or otherwise. "
         "Have them changed."),
    Rule("api_key", "API key, token or secret", CREDENTIAL, HIGH,
         _p(r"\b(?:api[_\s-]?key|secret[_\s-]?key|access[_\s-]?token|"
            r"bearer|client[_\s-]?secret|private[_\s-]?key)\b\s*[:=]?\s*\S{8,}"),
         "An access credential appears in this file. Have it revoked."),
    Rule("private_key", "Cryptographic private key", CREDENTIAL, HIGH,
         _p(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
         "A private key is embedded in this file."),
    Rule("connection_string", "Database or server connection string",
         INTERNAL, HIGH,
         _p(r"\b(?:jdbc:|mongodb(?:\+srv)?://|postgres(?:ql)?://|mysql://|"
            r"server\s*=\s*[\w.\\]+;\s*(?:uid|user)\s*=)"),
         "Internal system connection details were found."),
    Rule("internal_host", "Internal address or path", INTERNAL, MEDIUM,
         _p(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|"
            r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|localhost:\d+|"
            r"[A-Za-z]:\\Users\\[^\s\\]+)"),
         "An internal network address or a staff member's file path was found."),

    # -- confidentiality markings ----------------------------------------
    Rule("marking_strict", "Marked STRICTLY CONFIDENTIAL", CONFIDENTIAL, HIGH,
         _p(r"\bstrictly\s+confidential\b"),
         "The document is marked as strictly confidential.", mask=False),
    Rule("marking_confidential", "Marked CONFIDENTIAL", CONFIDENTIAL, HIGH,
         _p(r"\bconfidential(?:ity)?\b"),
         "The word 'confidential' appears in the document.", mask=False),
    Rule("marking_internal", "Marked for internal use only", CONFIDENTIAL, HIGH,
         _p(r"\b(?:for\s+internal\s+use\s+only|internal\s+use\s+only|"
            r"internal\s+circulation\s+only|for\s+official\s+use\s+only)\b"),
         "The document is marked for internal use.", mask=False),
    Rule("marking_restricted", "Marked RESTRICTED or SENSITIVE",
         CONFIDENTIAL, HIGH,
         _p(r"\b(?:restricted|sensitive|classified)\b(?:\s+(?:document|"
            r"information|data|copy|material))?"),
         "The document carries a restriction marking.", mask=False),
    Rule("marking_no_distribution", "Marked not for public distribution",
         CONFIDENTIAL, HIGH,
         _p(r"\b(?:not\s+for\s+(?:public\s+)?(?:distribution|circulation|release|"
            r"publication)|do\s+not\s+(?:distribute|circulate|share)|"
            r"draft\s*[-–]\s*not\s+for\s+release)\b"),
         "The document says it is not to be distributed.", mask=False),

    # -- the paperwork that is nothing but personal data -------------------
    Rule("attendance_sheet", "Attendance sheet or participant list",
         PERSONAL, HIGH,
         _p(r"\b(?:attendance\s+sheet|registration\s+sheet|sign[-\s]?in\s+sheet|"
            r"list\s+of\s+participants|participants?'?\s+list|masterlist\s+of)\b"),
         "Attendance and participant lists carry names, positions, contact "
         "numbers and signatures, and are not published."),
    Rule("personal_data_sheet", "Personal Data Sheet or 201 file",
         PERSONAL, HIGH,
         _p(r"\b(?:personal\s+data\s+sheet|\bpds\b|201\s+file|service\s+record|"
            r"statement\s+of\s+assets|\bsaln\b|bio[-\s]?data|curriculum\s+vitae|"
            r"\bresum[eé]\b)\b"),
         "This is an employee record. It must not be published."),
    Rule("beneficiary_list", "Beneficiary or household list", PERSONAL, HIGH,
         _p(r"\b(?:list\s+of\s+beneficiaries|beneficiar(?:y|ies)\s+(?:list|"
            r"masterlist|data)|household\s+(?:list|profile|survey)|"
            r"\b4ps\b|payroll)\b"),
         "Beneficiary and household data identifies private individuals."),

    # -- identifying details ----------------------------------------------
    Rule("signature", "Signature block", PERSONAL, MEDIUM,
         _p(r"(?:signature\s+over\s+printed\s+name|signature\s*[:_]|"
            r"\(sgd\.?\)|conforme\s*[:_]|signed\s*[:_])"),
         "Handwritten signatures are personal data and are normally removed "
         "before release.", mask=False),
    Rule("mobile", "Mobile telephone number", PERSONAL, MEDIUM,
         _p(r"(?:\+?63|\b0)9\d{2}[-\s]?\d{3}[-\s]?\d{4}\b"),
         "A mobile number was found. Publish an office line, never a personal "
         "one."),
    Rule("landline", "Landline telephone number", PERSONAL, MEDIUM,
         _p(r"(?:\+?63[-\s]?)?\(?0?8[5-8]\)?[-\s]?\d{3}[-\s]?\d{4}\b"),
         "A landline number was found. Check that it is an office line."),
    Rule("personal_email", "Personal email address", PERSONAL, MEDIUM,
         _p(r"\b[\w.+-]+@(?:gmail|yahoo|hotmail|outlook|ymail|icloud|proton"
            r"(?:mail)?)\.[\w.]{2,}\b"),
         "A personal email address was found. Publish an official address "
         "instead."),
    Rule("email", "Email address", PERSONAL, LOW,
         _p(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
         "Email addresses were found. Confirm each one is an official "
         "address the office means to publish.", mask=False),
    Rule("birthdate", "Date of birth", PERSONAL, MEDIUM,
         _p(r"\b(?:date\s+of\s+birth|birth\s*date|birthday|d\.?o\.?b\.?)\b\s*[:\-]?\s*\S+"),
         "A date of birth is personal data."),
    Rule("home_address", "Residential address", PERSONAL, MEDIUM,
         _p(r"\b(?:home|residential|house|permanent)\s+address\b\s*[:\-]?|"
            r"\b(?:blk|block)\.?\s*\d+[,\s]+(?:lot|l)\.?\s*\d+|"
            r"\bpurok\s+\w+|\bzone\s+\d+\b[^\n]{0,30}\bbrgy"),
         "A residential address identifies a private household."),
    Rule("named_person", "Named individual", PERSONAL, MEDIUM,
         _p(r"\b(?:name\s+of\s+(?:participant|beneficiary|employee|respondent|"
            r"applicant|owner)|full\s+name|printed\s+name|last\s+name|"
            r"first\s+name|middle\s+(?:name|initial))\b\s*[:\-]?"),
         "A field labelled as somebody's name was found. Check who is named "
         "and whether they consented to being published.", mask=False),
    Rule("honorific_name", "Person named with a title", PERSONAL, LOW,
         _p(r"\b(?:Mr|Mrs|Ms|Dr|Hon|Atty|Engr|Arch|Rev|Gov|Mayor|Brgy\.?\s*Capt)"
            r"\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z.]+){1,3}", re.NOFLAG),
         "Individuals are named in this document. Officials named in their "
         "official capacity are normally fine; private citizens are not.",
         mask=False),
]


def _mask(value):
    """
    Hide most of a match before it is stored or shown.

    The review screen has to say enough for a reviewer to find the problem in
    the file and no more. Printing the ID number in full would put it in the
    database a second time, in the audit trail, and on the screen of whoever
    is standing behind the reviewer.
    """
    value = " ".join(value.split())[:60]
    if len(value) <= 4:
        return "*" * len(value)
    keep = 2 if len(value) < 12 else 4
    head, tail = value[:keep], value[-2:]
    return f"{head}{'*' * min(len(value) - keep - 2, 12)}{tail}"


def _context_snippet(text, start, end, width=45):
    """A short window around a match, with every digit blanked out."""
    left = max(0, start - width)
    right = min(len(text), end + width)
    snippet = " ".join(text[left:right].split())
    snippet = re.sub(r"\d", "*", snippet)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def detect(extraction):
    """
    Run every rule over every readable segment.

    Returns a list of finding dictionaries, most serious first, each naming
    what was found, how often, where, and a masked example.
    """
    order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    collected = {}

    for segment in extraction.segments:
        text = segment.text
        if not text.strip():
            continue
        for rule in RULES:
            for match in rule.pattern.finditer(text):
                value = match.group(0)
                if rule.context and not any(
                    word in text[max(0, match.start() - 120):match.end() + 120].lower()
                    for word in rule.context
                ):
                    continue

                finding = collected.setdefault(rule.code, {
                    "code": rule.code,
                    "label": rule.label,
                    "category": rule.category,
                    "severity": rule.severity,
                    "advice": rule.advice,
                    "count": 0,
                    "evidence": [],
                    "locations": [],
                })
                finding["count"] += 1
                if segment.label not in finding["locations"]:
                    finding["locations"].append(segment.label)
                if len(finding["evidence"]) < MAX_EVIDENCE_PER_FINDING:
                    example = (
                        _mask(value) if rule.mask
                        else _context_snippet(text, match.start(), match.end())
                    )
                    if example not in finding["evidence"]:
                        finding["evidence"].append(example)

    findings = list(collected.values())

    # An email address that was already reported as a personal one should not
    # be counted twice under the general rule.
    if any(f["code"] == "personal_email" for f in findings):
        findings = [f for f in findings if f["code"] != "email"]
    # The same for the two confidentiality markings that overlap.
    if any(f["code"] == "marking_strict" for f in findings):
        findings = [f for f in findings if f["code"] != "marking_confidential"]

    findings.sort(key=lambda f: (order.get(f["severity"], 3), -f["count"]))
    return findings


def coverage_findings(extraction, document_label):
    """
    Turn what the scanner *could not* do into findings of its own.

    This is the part that keeps the screening honest. A scanned PDF produces
    no matches, and without this it would arrive at the reviewer looking
    identical to a file that was read end to end and found clean.
    """
    findings = []
    if not extraction.has_text:
        findings.append({
            "code": "unreadable",
            "label": "The file's contents could not be read",
            "category": COVERAGE,
            "severity": MEDIUM,
            "count": 1,
            "evidence": [],
            "locations": [],
            "advice": (
                f"Nothing in {document_label} has been screened. Open the file "
                "and read it in full before deciding."
            ),
        })
    elif not extraction.complete:
        findings.append({
            "code": "partial_read",
            "label": "Only part of the file could be read",
            "category": COVERAGE,
            "severity": MEDIUM,
            "count": 1,
            "evidence": [],
            "locations": [],
            "advice": (
                "The screening below covers only the part of the file the "
                "scanner could read. Treat it as incomplete."
            ),
        })
    return findings


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(findings):
    """
    Turn a list of findings into the risk level shown to the reviewer.

    Note what is *not* here: no branch returns an approval, and there is no
    threshold above which the file is released automatically. LOW is the
    floor, and LOW means "nothing was found", which is a statement about the
    scanner and not about the document.
    """
    from .models import RiskLevel

    if any(finding["severity"] == HIGH for finding in findings):
        return RiskLevel.HIGH
    if findings:
        return RiskLevel.REVIEW_REQUIRED
    return RiskLevel.LOW


def screen_document(document, save=True):
    """
    Screen one uploaded document and record the result on it.

    Never raises. A scanner that crashes on a malformed file must not take the
    upload with it - but nor may it leave the document looking screened, so a
    failure is recorded as a finding and the document is marked as needing
    review.
    """
    from .models import DocumentStatus, RiskLevel

    document.status = DocumentStatus.SCREENING
    if save:
        document.save(update_fields=["status"])

    try:
        document.file.open("rb")
        try:
            data = document.file.read()
        finally:
            document.file.close()
    except Exception as exc:
        logger.exception("Could not read document %s for screening", document.pk)
        document.risk_level = RiskLevel.REVIEW_REQUIRED
        document.text_extracted = False
        document.screening_findings = [{
            "code": "read_failed",
            "label": "The stored file could not be opened",
            "category": COVERAGE,
            "severity": MEDIUM,
            "count": 1,
            "evidence": [],
            "locations": [],
            "advice": f"The file could not be read from storage ({exc.__class__.__name__}).",
        }]
        document.screening_notes = "The file could not be opened for screening."
        document.screened_at = timezone.now()
        document.status = DocumentStatus.SCREENED
        if save:
            document.save()
        return document

    extraction = extract(data, document.extension)
    findings = detect(extraction) + coverage_findings(extraction, document.title or "this file")

    document.risk_level = classify(findings)
    document.screening_findings = findings
    document.text_extracted = extraction.has_text
    document.screening_notes = _notes_text(extraction, len(data))
    document.screened_at = timezone.now()
    document.status = DocumentStatus.SCREENED
    if save:
        document.save()

    logger.info(
        "Screened PPA document %s: %s, %d finding(s), read by %s",
        document.pk, document.risk_level, len(findings), extraction.method or "nothing",
    )
    return document


def _notes_text(extraction, size):
    lines = [
        f"Read by: {extraction.method or 'no reader available'}.",
        f"File size: {size:,} bytes.",
        "Coverage: "
        + ("the whole file was read." if extraction.complete
           else "the file was read only partly - see the findings."),
    ]
    if extraction.segments:
        lines.append(
            "Parts read: " + ", ".join(s.label for s in extraction.segments[:12])
            + ("..." if len(extraction.segments) > 12 else "")
        )
    lines.extend(extraction.notes)
    return "\n".join(lines)
