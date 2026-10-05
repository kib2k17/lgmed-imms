"""Emails sent to account holders."""

import logging
import secrets

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from core.context_processors import AGENCY

logger = logging.getLogger(__name__)

# No 0/O, 1/l/I: the password is read off an email and typed by hand.
_LOWER = "abcdefghjkmnpqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGITS = "23456789"
_SYMBOLS = "!@#$%*?"


def generate_temporary_password(length=12):
    """A random password with at least one of each character kind."""
    pools = [_LOWER, _UPPER, _DIGITS, _SYMBOLS]
    everything = "".join(pools)
    chars = [secrets.choice(pool) for pool in pools]
    chars += [secrets.choice(everything) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def send_welcome_email(user, password, request=None):
    """
    Welcome a new account holder with their role, username and temporary
    password. Returns True when the message was handed to the mail server.

    Never raises: the account already exists, and a mail server that is down
    must not turn a successful creation into an error page. The caller tells
    the administrator when it returns False.
    """
    if not user.email:
        return False

    login_path = reverse("accounts:login")
    context = {
        "user": user,
        "password": password,
        "role": user.get_role_display(),
        "login_url": request.build_absolute_uri(login_path) if request else login_path,
        "agency": AGENCY,
    }
    subject = f"Welcome to {AGENCY['system_name']} - your account details"
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("emails/welcome.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(render_to_string("emails/welcome.html", context), "text/html")

    try:
        message.send()
    except Exception:
        logger.exception("Welcome email to %s could not be sent", user.email)
        return False
    return True


def send_account_created_notice(user, created_by, request=None):
    """
    Tell ACCOUNT_NOTIFY_EMAILS that an account was created. Returns True when
    the message was handed to the mail server, False when there was no one to
    tell or it could not be sent.

    Deliberately without the temporary password: that goes to the account
    holder alone, so a copy sitting in a second inbox cannot be used to sign
    in as them. Never raises, for the same reason as the welcome email.
    """
    recipients = [
        address for address in settings.ACCOUNT_NOTIFY_EMAILS
        if address.lower() != (user.email or "").lower()
    ]
    if not recipients:
        return False

    detail_path = user.get_absolute_url()
    context = {
        "user": user,
        "created_by": created_by,
        "role": user.get_role_display(),
        "detail_url": request.build_absolute_uri(detail_path) if request else detail_path,
        "agency": AGENCY,
    }
    message = EmailMultiAlternatives(
        subject=(
            f"{AGENCY['system_name']}: new account created for "
            f"{user.get_display_name()}"
        ),
        body=render_to_string("emails/account_created.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    message.attach_alternative(
        render_to_string("emails/account_created.html", context), "text/html"
    )

    try:
        message.send()
    except Exception:
        logger.exception(
            "Account-created notice for %s could not be sent", user.username
        )
        return False
    return True
