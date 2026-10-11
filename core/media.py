"""
The only way to a file under MEDIA_ROOT.

MEDIA_ROOT holds two kinds of file side by side: what the public website shows
(announcement photographs, published reports, cleared accomplishment photos,
the approved copies of PPA documents) and what it must never show (incoming
correspondence, outgoing replies, monitoring attachments, the document
register, every unpublished draft). Their paths are predictable - a year, a
month, the name the file was uploaded under - so a web server that maps
/media/ straight onto the directory hands every one of them to anyone who
guesses a URL.

So nothing maps it. Every /media/ request comes here, the file is traced back
to the record it belongs to, and the record decides:

  * released to the public  -> anyone, while the public website is switched on;
  * anything else           -> a signed-in, active account that may open the
                               record's module (Menu Permissions included) and,
                               where the module restricts records further, that
                               record.

A path no record claims is a 404, the same answer as a path that does not
exist, so the gateway cannot be used to discover which files are on disk.

The templates keep using `{{ field.url }}`: the URL is unchanged, only what
answers it.
"""

import mimetypes
import posixpath
from dataclasses import dataclass
from typing import Callable

from django.apps import apps
from django.http import FileResponse, Http404
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_safe

# Shown in the browser (the in-page PDF viewer, an <img>). Anything else is
# handed over as a download, so an uploaded .html or .svg can never run as a
# page on this site's origin.
INLINE_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp",
    "image/tiff",
}


@dataclass(frozen=True)
class Source:
    """One model field whose files live under MEDIA_ROOT."""

    model: str                      # "app_label.ModelName"
    field: str
    module: str                     # Menu Permissions key (accounts/menu_access.py)
    is_public: Callable = None      # (obj) -> bool: released to the public website
    may_view: Callable = None       # (user, obj) -> bool: beyond module access


# -- public-release rules: the same querysets the public pages are built from


def _announcement_public(item):
    return type(item).objects.published().filter(pk=item.pk).exists()


def _report_public(report):
    from reports.models import ReportStatus

    return report.status == ReportStatus.PUBLISHED


def _update_attachment_public(attachment):
    from updates.models import public_periods

    return bool(
        attachment.is_public
        and public_periods().filter(pk=attachment.update.period_id).exists()
    )


def _document_public(document):
    return type(document).objects.public().filter(pk=document.pk).exists()


def _ppa_public_copy(document):
    from programs import public as ppa

    owner = document.owner
    return bool(document.public_url is not None and owner is not None and ppa.visible(owner))


# -- record-level rules for signed-in staff


def _document_visible(user, document):
    return type(document).objects.visible_to(user).filter(pk=document.pk).exists()


def _version_visible(user, version):
    return _document_visible(user, version.document)


SOURCES = (
    Source("announcements.Announcement", "image", "announcements",
           is_public=_announcement_public),
    Source("reports.Report", "file", "reports", is_public=_report_public),
    Source("updates.UpdateAttachment", "file", "updates",
           is_public=_update_attachment_public),
    Source("documents.Document", "file", "documents",
           is_public=_document_public, may_view=_document_visible),
    Source("documents.DocumentVersion", "file", "documents",
           may_view=_version_visible),
    Source("documents.SupportingFile", "file", "documents",
           may_view=_version_visible),
    Source("incoming.IncomingDocument", "attachment", "incoming"),
    Source("incoming.IncomingUpdate", "attachment", "incoming"),
    Source("outgoing.OutgoingDocument", "file", "outgoing"),
    Source("monitoring.MonitoringAttachment", "file", "monitoring"),
    Source("programs.SupportingDocument", "public_file", "programs",
           is_public=_ppa_public_copy),
)


def clean_path(path):
    """The stored name a URL path refers to, or None if it tries to leave MEDIA_ROOT."""
    if not path or "\x00" in path or "\\" in path or path.startswith("/"):
        return None
    normalised = posixpath.normpath(path)
    if normalised != path or normalised.startswith("..") or "/../" in f"/{normalised}/":
        return None
    return normalised


def owners(name):
    """(source, record) for every record whose file is stored under `name`."""
    for source in SOURCES:
        model = apps.get_model(source.model)
        for obj in model.objects.filter(**{source.field: name}):
            yield source, obj


def _public_site_on():
    from administration.models import SystemSetting

    return SystemSetting.load().public_site_enabled


def _staff_may_view(user, source, obj):
    from accounts.menu_access import can_access_module

    if not (user.is_authenticated and user.can_view):
        return False
    if not can_access_module(user, source.module):
        return False
    return source.may_view is None or source.may_view(user, obj)


def decide(user, name):
    """
    "public", "staff" or None: whether, and on what footing, `user` may have
    the file stored as `name`.
    """
    granted = None
    for source, obj in owners(name):
        if source.is_public is not None and source.is_public(obj) and _public_site_on():
            return "public"
        if granted is None and _staff_may_view(user, source, obj):
            granted = "staff"
    return granted


@require_safe
@xframe_options_sameorigin
def serve(request, path):
    from django.core.files.storage import default_storage

    name = clean_path(path)
    if name is None:
        raise Http404("No such file.")

    footing = decide(request.user, name)
    if footing is None:
        # The same answer whether the file is missing, unclaimed, or simply not
        # this person's to read: a 403 here would confirm the file exists.
        raise Http404("No such file.")

    try:
        handle = default_storage.open(name, "rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404("No such file.")

    filename = posixpath.basename(name)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    inline = content_type in INLINE_TYPES
    response = FileResponse(
        handle,
        as_attachment=not inline,
        filename=filename,
        content_type=content_type if inline else "application/octet-stream",
    )
    if footing == "public":
        response["Cache-Control"] = "public, max-age=3600"
    else:
        # Internal papers: kept by the reader's own browser at most, never by a
        # shared proxy, and never indexed.
        response["Cache-Control"] = "private, no-cache"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response
