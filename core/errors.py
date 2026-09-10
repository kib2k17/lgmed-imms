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


def server_error(request):
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
