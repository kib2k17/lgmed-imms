"""
Does an uploaded file's content match the extension it claims?

An extension is only a name. A page saved as "minutes.pdf" is still a page,
and a program renamed "photo.jpg" is still a program. Each accepted format
starts with a recognisable signature, so the first bytes are read and compared
before the file is kept. Formats with no signature (CSV, plain text) are
checked for the one thing that betrays a binary or a web page instead.

This is a check against mistakes and casual disguise, not a malware scanner;
see docs/security/SECURITY_AUDIT.md for what scanning would add.
"""

import os

from django import forms

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # legacy Office (.doc/.xls/.ppt)
_ZIP = (b"PK\x03\x04", b"PK\x05\x06")          # OOXML (.docx/.xlsx/.pptx/.xlsm)

SIGNATURES = {
    "pdf": (b"%PDF-",),
    "doc": (_OLE,), "xls": (_OLE,), "ppt": (_OLE,),
    "docx": _ZIP, "xlsx": _ZIP, "pptx": _ZIP, "xlsm": _ZIP,
    "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
    "bmp": (b"BM",),
    "tif": (b"II*\x00", b"MM\x00*"), "tiff": (b"II*\x00", b"MM\x00*"),
}
TEXT_EXTENSIONS = {"csv", "txt"}
_MARKUP = (b"<!doctype", b"<html", b"<script", b"<svg", b"<?xml", b"<iframe")


def _head(uploaded, size=2048):
    position = uploaded.tell() if hasattr(uploaded, "tell") else 0
    uploaded.seek(0)
    head = uploaded.read(size)
    uploaded.seek(position)
    return head or b""


def check_signature(uploaded):
    """Raise ValidationError when the content contradicts the extension."""
    if not uploaded:
        return uploaded
    extension = os.path.splitext(uploaded.name)[1].lstrip(".").lower()
    head = _head(uploaded)

    if extension == "webp":
        ok = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    elif extension in SIGNATURES:
        ok = head.startswith(SIGNATURES[extension])
    elif extension in TEXT_EXTENSIONS:
        lowered = head.lstrip().lower()
        ok = b"\x00" not in head and not lowered.startswith(_MARKUP)
    else:
        # Not a format this check knows: the caller's extension list decides.
        return uploaded

    if not ok:
        raise forms.ValidationError(
            f"The file's contents do not match its '.{extension}' extension. "
            "Save it again in that format and upload the new copy."
        )
    return uploaded
