"""
Carries the current request to the audit signal handlers, and records the
refusals that matter.
"""

from django.core.exceptions import PermissionDenied

from .models import Action
from .recording import record, reset_request, set_request


class AuditMiddleware:
    """
    Publishes the request on a context variable for the duration of the view.

    A context variable rather than thread-local storage: it behaves correctly
    under ASGI, and it is reset in a finally block so a request never leaks
    into the worker's next piece of work.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_request(token)

    def process_exception(self, request, exception):
        """A user reaching for something their role forbids is worth recording."""
        if isinstance(exception, PermissionDenied):
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                record(
                    Action.ACCESS_DENIED,
                    request=request,
                    detail=f"Access refused to {request.path}",
                )
        return None
