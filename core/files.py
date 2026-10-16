"""
Showing a stored file in the browser rather than handing it over as a download.

The in-system PDF viewer (templates/includes/pdf_viewer.html) frames the file
on the same page. The site refuses to be framed at all (X_FRAME_OPTIONS =
"DENY"), so the views that feed the viewer relax that for their own responses
only, and only to the site itself - see `xframe_options_sameorigin` where they
are declared. Each such view re-checks access exactly as the matching download
does; viewing a file is not a way round a restriction on downloading it.

Who sends the bytes
-------------------
By default Django streams the file itself. With LGMED_ACCEL_REDIRECT on, the
view still decides - every access check runs exactly as before - but answers
with an X-Accel-Redirect header naming the file, and nginx sends it from an
`internal` location no browser can request directly (deploy/nginx). A large
PDF then no longer occupies the single Daphne process for as long as the
download takes.
"""

import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.utils.http import content_disposition_header

# The nginx locations that alias the two roots. `internal` there, so only an
# X-Accel-Redirect from this application can reach them.
ACCEL_PREFIXES = (
    ("MEDIA_ROOT", "/_internal/media/"),
    ("PROTECTED_MEDIA_ROOT", "/_internal/protected/"),
)


def is_pdf(fieldfile):
    """Whether a stored file is a PDF, judged by its name."""
    name = getattr(fieldfile, "name", "") or ""
    return name.lower().endswith(".pdf")


def _accel_location(storage, name):
    """The internal nginx path for a stored file, or None if it has none."""
    location = getattr(storage, "location", None)
    if not location:
        return None
    root = Path(location).resolve()
    for setting, prefix in ACCEL_PREFIXES:
        configured = getattr(settings, setting, None)
        if configured and Path(configured).resolve() == root:
            return prefix + quote(name.replace(os.sep, "/"))
    return None


MISSING = (
    "The file recorded here is not present in storage. Report this to the "
    "system administrator."
)


def send_stored(storage, name, *, filename=None, as_attachment=True, content_type=None):
    """
    Hand over a stored file after the caller has checked access.

    Streamed by Django, or by nginx when LGMED_ACCEL_REDIRECT is on and the
    file lives under one of the two roots. Raises Http404 when the file is
    missing either way, so a broken record reads the same in both modes.
    """
    filename = filename or os.path.basename(name)
    content_type = (
        content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )

    accel = getattr(settings, "LGMED_ACCEL_REDIRECT", False) and _accel_location(storage, name)
    if accel:
        try:
            present = storage.exists(name)
        except (OSError, ValueError):
            present = False
        if not present:
            raise Http404(MISSING)
        response = HttpResponse(content_type=content_type)
        response["Content-Disposition"] = content_disposition_header(as_attachment, filename)
        response["X-Accel-Redirect"] = accel
        return response

    try:
        handle = storage.open(name, "rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404(MISSING)
    return FileResponse(
        handle, as_attachment=as_attachment, filename=filename, content_type=content_type
    )


def send_fieldfile(fieldfile, **kwargs):
    """`send_stored` for a model's FileField value."""
    if not fieldfile:
        raise Http404("No file is attached.")
    return send_stored(fieldfile.storage, fieldfile.name, **kwargs)


def serve_inline(fieldfile):
    """
    Show a stored file in the browser - or, unless it is a PDF or a picture,
    hand it over as a download.

    A file the database knows about but storage does not reads as "not here",
    not as a server fault.
    """
    if not fieldfile:
        raise Http404("No file is attached.")
    from .media import INLINE_TYPES

    filename = os.path.basename(fieldfile.name)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    # Only PDFs and pictures are shown in place. Anything else - above all an
    # uploaded .html or .svg, which a browser would run as a page of this
    # site - is handed over as a download instead.
    if content_type not in INLINE_TYPES:
        return send_fieldfile(
            fieldfile, filename=filename, as_attachment=True,
            content_type="application/octet-stream",
        )
    return send_fieldfile(
        fieldfile, filename=filename, as_attachment=False, content_type=content_type
    )

