"""
Showing a stored file in the browser rather than handing it over as a download.

The in-system PDF viewer (templates/includes/pdf_viewer.html) frames the file
on the same page. The site refuses to be framed at all (X_FRAME_OPTIONS =
"DENY"), so the views that feed the viewer relax that for their own responses
only, and only to the site itself - see `xframe_options_sameorigin` where they
are declared. Each such view re-checks access exactly as the matching download
does; viewing a file is not a way round a restriction on downloading it.
"""

import mimetypes
import os

from django.http import FileResponse, Http404


def is_pdf(fieldfile):
    """Whether a stored file is a PDF, judged by its name."""
    name = getattr(fieldfile, "name", "") or ""
    return name.lower().endswith(".pdf")


def serve_inline(fieldfile):
    """
    Stream a stored file for display in the browser.

    A file the database knows about but storage does not reads as "not here",
    not as a server fault.
    """
    if not fieldfile:
        raise Http404("No file is attached.")
    try:
        handle = fieldfile.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404(
            "The file recorded here is not present in storage. Report this to "
            "the system administrator."
        )
    filename = os.path.basename(fieldfile.name)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(
        handle, as_attachment=False, filename=filename, content_type=content_type
    )
