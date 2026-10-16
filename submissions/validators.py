"""
Is an uploaded MMIA or DTR what it says it is?

Checked on the server, on the file's content, whatever the browser claimed:

  1. the extension is one of PDF, DOC, DOCX, XLS, XLSX;
  2. it is not empty and not over MONTHLY_SUBMISSION_MAX_UPLOAD_MB;
  3. its first bytes are that format's signature (core/uploads.py) - a page
     or a program renamed "dtr.pdf" is refused;
  4. a DOCX or XLSX is a real Office package of the right kind, and carries
     no macros - an .xlsm renamed .xlsx is refused;
  5. a PDF carries no scripts, launch actions or embedded files.

This guards against mistakes and casual disguise. It is not a virus scanner;
on the server, on-access antivirus over the protected folder does that job
(docs/security/).
"""

import io
import os
import re
import zipfile

from django import forms
from django.conf import settings

from core.uploads import check_signature

from .models import ALLOWED_EXTENSIONS

# PDF name objects that run code or carry other files. Matched as whole names
# so /JSxxx in ordinary text does not trip it; the "#" escape form (/J#61va...)
# is decoded first.
_PDF_ACTIVE = re.compile(
    rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|XFA)(?![A-Za-z0-9])"
)
_PDF_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")

_OOXML_MAIN_PART = {"docx": "word/", "xlsx": "xl/"}
_MACRO_PARTS = ("vbaproject.bin", "vbadata.xml")
_MAX_ZIP_ENTRIES = 5000
_MAX_UNCOMPRESSED = 200 * 1024 * 1024


def max_upload_bytes():
    return settings.MONTHLY_SUBMISSION_MAX_UPLOAD_MB * 1024 * 1024


def _read_all(uploaded):
    uploaded.seek(0)
    data = uploaded.read()
    uploaded.seek(0)
    return data


def _check_pdf(data):
    decoded = _PDF_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), data)
    if _PDF_ACTIVE.search(decoded):
        raise forms.ValidationError(
            "This PDF contains scripts, embedded files or automatic actions, "
            "which are not accepted. Print it to a new PDF (Microsoft Print to "
            "PDF) and upload that copy."
        )


def _check_ooxml(data, extension):
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
        entries = package.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        raise forms.ValidationError(
            f"This .{extension} file is damaged or is not a real Office "
            "document. Save it again from Word or Excel and upload the new copy."
        )
    names = [entry.filename.replace("\\", "/").lower() for entry in entries]
    if (
        len(entries) > _MAX_ZIP_ENTRIES
        or sum(entry.file_size for entry in entries) > _MAX_UNCOMPRESSED
    ):
        raise forms.ValidationError("This file is not an ordinary Office document.")
    if "[content_types].xml" not in names or not any(
        name.startswith(_OOXML_MAIN_PART[extension]) for name in names
    ):
        raise forms.ValidationError(
            f"The file's contents do not match its '.{extension}' extension. "
            "Save it again in that format and upload the new copy."
        )
    if any(name.rsplit("/", 1)[-1] in _MACRO_PARTS for name in names):
        raise forms.ValidationError(
            "This document contains macros, which are not accepted. Save it "
            f"again as a plain .{extension} file and upload that copy."
        )


def validate_submission_file(uploaded):
    """Raise ValidationError unless `uploaded` is an acceptable MMIA or DTR."""
    if not uploaded:
        raise forms.ValidationError("Choose a file to upload.")

    extension = os.path.splitext(uploaded.name or "")[1].lstrip(".").lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise forms.ValidationError(
            "Only PDF, Word (.doc, .docx) and Excel (.xls, .xlsx) files are accepted."
        )
    if not uploaded.size:
        raise forms.ValidationError("The file is empty.")
    if uploaded.size > max_upload_bytes():
        raise forms.ValidationError(
            f"The file is larger than the "
            f"{settings.MONTHLY_SUBMISSION_MAX_UPLOAD_MB} MB limit."
        )

    check_signature(uploaded)

    data = _read_all(uploaded)
    if extension == "pdf":
        _check_pdf(data)
    elif extension in _OOXML_MAIN_PART:
        _check_ooxml(data, extension)
    return uploaded


def clean_display_name(name):
    """
    The original filename, safe to show and to offer as a download name.

    Only the last path component, no control characters, at most 200
    characters with the extension kept.
    """
    base = os.path.basename((name or "").replace("\\", "/"))
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"/\\|?*')
    base = base.strip(" .") or "document"
    stem, extension = os.path.splitext(base)
    return stem[: 200 - len(extension)] + extension.lower()
