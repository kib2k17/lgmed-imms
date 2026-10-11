"""Branded error pages - part of the Security UX requirements (section 23)."""

from django.shortcuts import render


def permission_denied(request, exception=None):
    return render(
        request,
        "errors/error.html",
        {
            "code": "403",
            "title": "Access not permitted",
            "message": (
                "Your account does not have permission to open this page. "
                "If you believe this is an error, contact the LGMED system "
                "administrator."
            ),
            "icon": "lock",
        },
        status=403,
    )


def page_not_found(request, exception=None):
    return render(
        request,
        "errors/error.html",
        {
            "code": "404",
            "title": "Page not found",
            "message": (
                "The page you requested does not exist or may have been moved."
            ),
            "icon": "help",
        },
        status=404,
    )


_PLAIN_500 = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>System error</title></head><body style=\"font-family:sans-serif;"
    "max-width:40rem;margin:4rem auto;padding:0 1rem\"><h1>System error</h1>"
    "<p>The system encountered an unexpected error. Please try again, or "
    "contact ICT support if the problem persists.</p></body></html>"
)


def server_error(request):
    """
    The branded page when it can be drawn, a plain one when it cannot.

    The branded page runs the context processors, which read the database;
    when the database is what failed, rendering it fails too, and the visitor
    would get whatever the server falls back to. Never any detail either way.
    """
    try:
        return _branded_server_error(request)
    except Exception:  # noqa: BLE001 - the last line of defence must not raise
        from django.http import HttpResponseServerError

        return HttpResponseServerError(_PLAIN_500)


def _branded_server_error(request):
    return render(
        request,
        "errors/error.html",
        {
            "code": "500",
            "title": "System error",
            "message": (
                "The system encountered an unexpected error. The incident has "
                "been logged. Please try again, or contact ICT support if the "
                "problem persists."
            ),
            "icon": "warning",
        },
        status=500,
    )
