"""
Deployment checks of this system's own, run by `manage.py check --deploy`.

Django's checks cover Django's settings. These cover the ones a production
LGMED-IMMS needs and Django cannot know about. Each is a warning rather than
an error: some are legitimate on a particular network (no reCAPTCHA on an
office intranet, for instance), and the person deploying should decide that
knowingly rather than discover it later.
"""

from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def production_settings(app_configs, **kwargs):
    warnings = []

    if not settings.ESIRA_CREDENTIAL_KEY:
        warnings.append(Warning(
            "ESIRA_CREDENTIAL_KEY is not set: stored signing certificates are "
            "encrypted with a key derived from SECRET_KEY, so rotating "
            "SECRET_KEY after a leak makes every stored certificate unreadable.",
            hint="Generate a Fernet key (see .env.example) and keep it out of database backups.",
            id="lgmed.W001",
        ))

    if not (settings.RECAPTCHA_SITE_KEY and settings.RECAPTCHA_SECRET_KEY):
        warnings.append(Warning(
            "reCAPTCHA is not configured for the sign-in page.",
            hint="The sign-in throttle still applies. Configure RECAPTCHA_* if the "
                 "sign-in page is reachable from the internet.",
            id="lgmed.W002",
        ))

    if settings.CACHES["default"]["BACKEND"].endswith("LocMemCache"):
        warnings.append(Warning(
            "The cache is per-process memory, so each server process keeps its "
            "own sign-in throttle counts.",
            hint="Fine for the single Daphne process the system runs as. With "
                 "several, set DJANGO_CACHE_LOCATION.",
            id="lgmed.W003",
        ))

    if settings.SECURE_SSL_REDIRECT and not getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        warnings.append(Warning(
            "SECURE_SSL_REDIRECT is on but DJANGO_BEHIND_TLS_PROXY is not: behind "
            "a TLS-terminating proxy every request will redirect to itself.",
            hint="Set DJANGO_BEHIND_TLS_PROXY=1 once the proxy overwrites X-Forwarded-Proto.",
            id="lgmed.W004",
        ))

    if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        warnings.append(Warning(
            "No EMAIL_HOST: welcome emails, including temporary passwords, are "
            "written to the server log instead of being sent.",
            hint="Configure EMAIL_HOST and friends before creating accounts.",
            id="lgmed.W005",
        ))

    return warnings
