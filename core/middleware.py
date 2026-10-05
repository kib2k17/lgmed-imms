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
