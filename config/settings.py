"""
Django settings for LGMED-iMMS.

Local Government Monitoring and Evaluation Division -
Information Management and Monitoring System
DILG Regional Office XIII - Caraga
"""

import os
from pathlib import Path

from .env import env, env_bool, env_float, env_list, load_venv_env, local_ipv4_addresses

BASE_DIR = Path(__file__).resolve().parent.parent

# Tops the environment up from <venv>/lgmed.env before anything below reads it,
# so secrets stay out of this file and out of the repository. Real environment
# variables are never overwritten. See config/env.py.
load_venv_env()


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-replace-before-deployment",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]


# ---------------------------------------------------------------------------
# Serving to the office network
# ---------------------------------------------------------------------------
#
# Set DJANGO_LAN_ACCESS=1 (in <venv>/lgmed.env) and this machine's own
# addresses are added to both lists above, so colleagues on the same network
# can open the server in their browser. See run-lan.ps1 and the README.
#
# It is worked out at start-up rather than written down because the address is
# a DHCP lease: it changes with the lease, with a reconnection, and with every
# move between office networks. A hand-written entry is stale by the next
# morning, and the failure it produces - Django's bare 400 "Invalid HTTP_HOST
# header" - reads as a broken site rather than as an out-of-date setting.
#
# DEBUG gates it, and that is deliberate. ALLOWED_HOSTS is what stops a request
# carrying a forged Host header from being answered, and a production host must
# name its own hostnames explicitly rather than accept whatever interface the
# machine happens to have. On a deployed server the flag does nothing, and it
# says so rather than leaving that to be discovered.
LAN_ACCESS = env_bool("DJANGO_LAN_ACCESS", False)

# The ports an origin is trusted on. CSRF compares scheme + host + PORT, so a
# server started on 8080 needs 8080 here; run-lan.ps1 sets this to the port it
# was asked for, so the ordinary case needs no thought.
LAN_PORTS = env_list("DJANGO_LAN_PORTS", "8000")

LAN_ADDRESSES: list[str] = []
if LAN_ACCESS and DEBUG:
    LAN_ADDRESSES = local_ipv4_addresses()
    for _address in LAN_ADDRESSES:
        if _address not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_address)
        for _port in LAN_PORTS:
            _origin = f"http://{_address}:{_port}"
            if _origin not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(_origin)
elif LAN_ACCESS:
    import warnings

    warnings.warn(
        "DJANGO_LAN_ACCESS is set but DEBUG is off, so it is ignored. "
        "A deployed server must name its hostnames in DJANGO_ALLOWED_HOSTS.",
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    "django.contrib.staticfiles",
    # LGMED-iMMS
    "accounts",
    "core",
    "lgus",
    "programs",
    "monitoring",
    "incoming",
    "services",
    "documents",
    "announcements",
    "reports",
    "activities",
    "updates",
    "administration",
    "audit",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Publishes the request to the audit signal handlers. Last, so it sees the
    # authenticated user and wraps the view that raises PermissionDenied.
    "audit.middleware.AuditMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_identity",
                "core.context_processors.navigation",
                "core.context_processors.system_settings",
                "core.context_processors.notifications",
                "core.context_processors.asset_version",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

SESSION_COOKIE_AGE = 60 * 60 * 8          # one working day
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# ---------------------------------------------------------------------------
# reCAPTCHA v3 on the sign-in form
#
# The keys are read from the environment and are deliberately absent from this
# file: it is committed, and a key written here would stay in the history for
# good. On this machine they come from <venv>/lgmed.env, which .gitignore
# excludes along with the rest of venv/. Django's own error page redacts any
# setting whose name contains KEY or SECRET, so neither appears in a traceback.
#
# With no keys configured the check is simply off, which is what keeps the
# tests and a fresh checkout working. RECAPTCHA_ENFORCE=0 keeps the check
# running but stops it refusing anyone - the verdicts still reach the audit
# log, which is how to try it out before switching it on for real.
# ---------------------------------------------------------------------------

RECAPTCHA_SITE_KEY = env("RECAPTCHA_SITE_KEY")
RECAPTCHA_SECRET_KEY = env("RECAPTCHA_SECRET_KEY")
RECAPTCHA_MIN_SCORE = env_float("RECAPTCHA_MIN_SCORE", 0.5)
RECAPTCHA_TIMEOUT = env_float("RECAPTCHA_TIMEOUT", 5.0)
RECAPTCHA_ENFORCE = env_bool("RECAPTCHA_ENFORCE", True)


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-ph"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Protected media
# ---------------------------------------------------------------------------
#
# MEDIA_ROOT is a *public* directory: the development server serves it wholesale
# (see config/urls.py) and in production the web server is configured to do the
# same. Anything written there is one guessed URL away from the internet.
#
# Internal documents - the supporting files staff upload against a programme,
# project or activity before anyone has cleared them - must therefore not live
# there. They are written to PROTECTED_MEDIA_ROOT, which no web server maps to a
# URL, and are read back only through an authenticated Django view that
# re-checks the user's role on every request.
#
# A file becomes publicly reachable only when an authorised reviewer approves it
# and the system writes a separate, approved copy into MEDIA_ROOT. Flipping a
# boolean on the internal file is deliberately not enough.
PROTECTED_MEDIA_ROOT = BASE_DIR / "protected"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Rooted at PROTECTED_MEDIA_ROOT and given no base_url, so asking a
    # protected file for its .url fails loudly rather than handing a template a
    # link that leaks the path. The location is read from the setting when the
    # storage is used - see programs/storage.py for why that matters.
    "protected": {"BACKEND": "programs.storage.ProtectedFileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
    },
}


# ---------------------------------------------------------------------------
# Messages -> maps onto the alert component styles
# ---------------------------------------------------------------------------

from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {
    message_constants.DEBUG: "info",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "danger",
}


# ---------------------------------------------------------------------------
# Security (production defaults; harmless in development)
# ---------------------------------------------------------------------------

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "1") == "1"

    # Behind Nginx (or any reverse proxy) terminating TLS and forwarding plain
    # HTTP, Django sees an insecure request, SECURE_SSL_REDIRECT sends it to
    # HTTPS, the proxy forwards it back over HTTP - and the site disappears
    # into a redirect loop with nothing obviously wrong in the log. This is
    # how Django is told to believe the proxy's header instead.
    #
    # Opt-in, and it must stay that way: a client can send X-Forwarded-Proto
    # itself. Trusting it when there is NO proxy in front - or one that passes
    # the client's own value through - lets anyone claim their plain HTTP
    # request arrived over TLS. Set this only once the proxy is known to
    # overwrite the header on every request.
    if os.environ.get("DJANGO_BEHIND_TLS_PROXY", "0") == "1":
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
