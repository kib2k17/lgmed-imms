"""
Deployment checks of this system's own, run by `manage.py check --deploy`.

Django's checks cover Django's settings. These cover the ones a production
LGMED-IMMS needs and Django cannot know about. Each is a warning rather than
an error: some are legitimate on a particular network (no reCAPTCHA on an
office intranet, for instance), and the person deploying should decide that
knowingly rather than discover it later.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security, deploy=True)
def production_settings(app_configs, **kwargs):
    warnings = []

    if not settings.ESIRA_CREDENTIAL_KEY:
        # An error in production, not a warning: without its own key, the one
        # response to a leaked SECRET_KEY - rotating it - destroys every stored
        # certificate, which is exactly the pressure to leave a leaked key in
        # place. The exception to the module's "warnings only" rule above.
        message = (
            "ESIRA_CREDENTIAL_KEY is not set: stored signing certificates are "
            "encrypted with a key derived from SECRET_KEY, so rotating "
            "SECRET_KEY after a leak makes every stored certificate unreadable."
        )
        hint = "Generate a Fernet key (see .env.example) and keep it out of database backups."
        if settings.DEBUG:
            warnings.append(Warning(message, hint=hint, id="lgmed.W001"))
        else:
            warnings.append(Error(message, hint=hint, id="lgmed.E001"))

    if not settings.LGMED_MFA_KEY:
        warnings.append(Warning(
            "LGMED_MFA_KEY is not set: authenticator secrets are encrypted with a "
            "key derived from SECRET_KEY, so rotating SECRET_KEY means every "
            "enrolled account must be reset and enrol again.",
            hint="Generate a Fernet key (see .env.example) and back it up with "
                 "ESIRA_CREDENTIAL_KEY, apart from the database backups.",
            id="lgmed.W006",
        ))

    if not settings.LGMED_CLAMAV_ADDRESS:
        warnings.append(Warning(
            "Uploads are not scanned for viruses (LGMED_CLAMAV_ADDRESS is not set).",
            hint="Install ClamAV (clamd) on the server and set LGMED_CLAMAV_ADDRESS, "
                 "or rely on endpoint protection on staff computers - see M-09 in "
                 "docs/security/SECURITY_AUDIT.md.",
            id="lgmed.W007",
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
