"""
Request handling shared by every module.
"""

from django.contrib.sessions.middleware import SessionMiddleware as DjangoSessionMiddleware


def mark_passive(request):
    """
    Declare that this request was made by the page, not by the person.

    The installed app asks the server for new notifications every minute or
    so while it is open. With SESSION_SAVE_EVERY_REQUEST on, each of those
    requests would push the session's expiry back, so a signed-in tab left
    open on an unattended desk would never time out - the one-working-day
    session would become a session for as long as the window stays open.
    A passive request reads the session but never extends it.
    """
    request.session_passive = True


class SessionMiddleware(DjangoSessionMiddleware):
    """Django's session middleware, except that passive requests are not saved."""

    def process_response(self, request, response):
        if getattr(request, "session_passive", False):
            return response
        return super().process_response(request, response)


class UploadScanMiddleware:
    """
    Scans every uploaded file with ClamAV before any view sees it (core/antivirus.py).

    Does nothing unless LGMED_CLAMAV_ADDRESS is set. An infected file stops
    the whole request - nothing in it is saved - and the refusal is written to
    the audit log with the file name and the signature found.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from . import antivirus

        if request.method != "POST" or not antivirus.is_enabled():
            return None
        if not request.content_type.startswith("multipart/form-data"):
            return None
        for uploaded in [f for _name, files in request.FILES.lists() for f in files]:
            try:
                verdict = antivirus.scan(uploaded)
            except antivirus.ScannerUnavailable as exc:
                antivirus.logger.error("Upload not scanned: %s", exc)
                from django.conf import settings

                if getattr(settings, "LGMED_CLAMAV_REQUIRED", False):
                    return self._refuse(
                        request, uploaded.name,
                        "The virus scanner is not available, so files cannot be "
                        "accepted right now. Please try again later.",
                        detail=f"Upload refused, scanner unavailable: {uploaded.name}",
                        status=503,
                    )
                continue
            if not verdict.clean:
                return self._refuse(
                    request, uploaded.name,
                    f"The file \u201c{uploaded.name}\u201d was blocked by the virus "
                    "scanner and nothing was saved. Do not open the original on "
                    "your computer; report it to the system administrator.",
                    detail=f"Upload blocked by the virus scanner: {uploaded.name} "
                           f"({verdict.signature})",
                    status=422,
                )
        return None

    @staticmethod
    def _refuse(request, name, message, *, detail, status):
        from django.shortcuts import render

        from audit.models import Action
        from audit.recording import record

        record(Action.ACCESS_DENIED, request=request, detail=detail[:500])
        return render(request, "errors/error.html", {
            "code": str(status),
            "title": "File not accepted",
            "message": message,
            "icon": "warning",
        }, status=status)
