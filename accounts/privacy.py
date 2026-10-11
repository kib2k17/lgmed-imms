"""
The Data Privacy Act notice shown after every sign-in.

LGMED-IMMS holds the personal information of LGU officials, focal persons and
DILG personnel, so everyone who signs in is reminded of their obligations under
Republic Act No. 10173 before they touch a record. The notice is owed on every
sign-in, not once per account: it is a reminder of a duty, and a duty agreed to
a year ago is easily forgotten. It therefore lives in the session, which a new
sign-in replaces, rather than on the user.

Each acknowledgement is written to the audit log, so the office can show who
agreed to the notice and when.
"""

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

SESSION_KEY = "privacy_notice_pending"


@receiver(user_logged_in)
def require_acknowledgement(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        request.session[SESSION_KEY] = True


def is_pending(request):
    return bool(request.session.get(SESSION_KEY))


def acknowledge(request):
    request.session.pop(SESSION_KEY, None)
