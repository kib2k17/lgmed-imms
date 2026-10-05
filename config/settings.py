"""
Django settings for LGMED-iMMS.

Local Government Monitoring and Evaluation Division -
Information Management and Monitoring System
DILG Regional Office XIII - Caraga
"""

import os
from pathlib import Path

from .env import env, env_bool, env_float, env_list, load_venv_env, local_ipv4_addresses
from .version import system_version

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
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,192.168.1.132").split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]


# The release the running code belongs to, shown in the footer of every page so
# "it still does the old thing" can be pinned to a build instead of guessed at.
# Read from the checkout rather than written down here, because a constant is
# only correct until the next edit: see config/version.py for the format. An
# entry in <venv>/lgmed.env still wins, for a deployment that stamps itself.
SYSTEM_VERSION = env("LGMED_SYSTEM_VERSION") or system_version(
    BASE_DIR, mark_uncommitted=DEBUG
)

# The regional identifier every LGMED code opens with, as in
# "LGMED-13 - RGFJ - 2023-01-03-0001". See outgoing/codes.py.
LGMED_CODE_PREFIX = env("LGMED_CODE_PREFIX", "LGMED-13")


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

# Two-step verification at sign-in. LGMED_MFA_OFF=1 in venv/lgmed.env skips
# the code step for everyone - for a developer locked out because the phone is
# elsewhere. Enrolments are kept, so removing the line restores them as they
# were. Development only: with DEBUG off it is ignored, and the code is always
# asked for.
MFA_OFF = (
    DEBUG
    and env_bool("LGMED_MFA_OFF", False)
    # The test suite always checks two-step verification as it really works.
    and "test" not in __import__("sys").argv[1:2]
)
if MFA_OFF:
    import warnings

    warnings.warn(
        "LGMED_MFA_OFF is set: two-step verification is skipped at sign-in. "
        "Remove it from venv/lgmed.env as soon as you have your phone.",
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    # Daphne first: it replaces `runserver` with one that also answers
    # WebSockets (core/consumers.py), so run-lan.ps1 needs no change.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    # django.contrib.staticfiles, leaving out the Tailwind source (core/apps.py).
    "core.apps.StaticFilesConfig",
    # LGMED-iMMS
    "accounts",
    "core",
    "lgus",
    "programs",
    "monitoring",
    "incoming",
    "outgoing",
    "datasync",
    "services",
    "documents",
    "announcements",
    "reports",
    "activities",
    "updates",
    "administration",
    "audit",
    "notifications",
    # LGMED Innovation Action
    "esira",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Django's own, except that it leaves the session's expiry alone for the
    # app's background notification checks. See core/middleware.py.
    "core.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Publishes the request to the audit signal handlers. Last, so it sees the
    # authenticated user and wraps the view that raises PermissionDenied.
    "audit.middleware.AuditMiddleware",
    # Refuses the URLs of a module closed from Menu Permissions. After the
    # audit middleware, so the refusal it records carries the request.
    "accounts.middleware.ModuleAccessMiddleware",
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
                "core.context_processors.privacy_notice",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# WebSockets, for what has to reach an open page the moment it happens - a
# full-screen system announcement (core/consumers.py). Served by Daphne.
ASGI_APPLICATION = "config.asgi.application"

# The channel layer carries a broadcast from the request that made it to every
# open socket. In memory is enough for one server process, which is how the
# system runs. A deployment with several processes must share one layer:
# install channels-redis and set LGMED_CHANNEL_REDIS_URL.
_channel_redis = os.environ.get("LGMED_CHANNEL_REDIS_URL", "").strip()
CHANNEL_LAYERS = {
    "default": (
        {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [_channel_redis]},
        }
        if _channel_redis
        else {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    )
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("MYSQL_DATABASE", "lgmedimms"),
        "USER": env("MYSQL_USER", "lgmedimms"),
        "PASSWORD": env("MYSQL_PASSWORD"),
        "HOST": env("MYSQL_HOST", "127.0.0.1"),
        "PORT": env("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        "TEST": {
            "CHARSET": "utf8mb4",
            "COLLATION": "utf8mb4_unicode_ci",
        },
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
# Signing out returns to the login page, not the public homepage: this is a
# staff-only system and the public pages carry no way back in.
LOGOUT_REDIRECT_URL = "accounts:login"

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
# Outgoing email (SMTP)
#
# Used for the welcome email a new account receives. Like the reCAPTCHA keys,
# the server and its password come from <venv>/lgmed.env and never from this
# file. With no EMAIL_HOST configured, messages are printed to the console
# instead of sent, so a fresh checkout and the tests never try to reach a
# mail server.
#
# For a Gmail sender: EMAIL_HOST=smtp.gmail.com, EMAIL_PORT=587,
# EMAIL_USE_TLS=1, and EMAIL_HOST_PASSWORD set to a Google *app password*
# (the account password is refused once 2-Step Verification is on).
# ---------------------------------------------------------------------------

EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = int(env("EMAIL_PORT", "587") or 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(env_float("EMAIL_TIMEOUT", 15))
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL") or (
    f"LGMED-iMMS <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "LGMED-iMMS <noreply@localhost>"
)

# Who is told when an account is created: comma-separated addresses, e.g. the
# system administrator. They receive the new account's name, username, email
# and role - never its temporary password, which goes to the account holder
# alone. Empty sends no notice.
ACCOUNT_NOTIFY_EMAILS = env_list("ACCOUNT_NOTIFY_EMAILS")


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
# e-SIRA - Electronic Signature, Identification, Routing and Approval
# ---------------------------------------------------------------------------
#
# e-SIRA keeps two things apart that are easy to confuse. Placing a signature
# box on a page is an interface act and proves nothing. Signing is a PAdES
# digital signature made with the signer's own DICT PNPKI private key, which
# is the only thing the signed PDF carries as proof. See docs/esira.md for the
# whole integration, and esira/signing/ for the backends.
#
# ESIRA_SIGNING_BACKEND
#   "pkcs12"   The signer presents their PNPKI certificate file (.p12/.pfx) and
#              its passphrase at the moment of signing. The key is held in
#              memory for that one request and never written to disk or the
#              database. This is how PNPKI individual certificates are issued.
#   "external" A signing agent on the signer's own computer (PKCS#11 token or
#              DICT middleware). Declared, not yet connected - the backend
#              refuses to sign and says what is missing. See docs/esira.md.
#
# ESIRA_PNPKI_TRUST_ROOTS
#   Comma-separated paths to the DICT PNPKI root and intermediate CA
#   certificates (PEM or DER), as published by DICT. A signing certificate is
#   only accepted as "PNPKI" when it chains to one of these. With none set, no
#   certificate can be trusted and signing is refused - unless the development
#   override below is on.
#
# ESIRA_ALLOW_UNTRUSTED_CERTIFICATES
#   Development and training only, and ignored unless DEBUG is on. Lets a test
#   certificate sign so the workflow can be exercised before the PNPKI chain is
#   installed. Every such signature is recorded and displayed as NOT PNPKI-
#   verified; it is never presented as one.
ESIRA_SIGNING_BACKEND = env("ESIRA_SIGNING_BACKEND", "pkcs12")
ESIRA_PNPKI_TRUST_ROOTS = env_list("ESIRA_PNPKI_TRUST_ROOTS")
ESIRA_ALLOW_UNTRUSTED_CERTIFICATES = DEBUG and env_bool(
    "ESIRA_ALLOW_UNTRUSTED_CERTIFICATES", False
)
# Fetch OCSP/CRL revocation data while validating a certificate. Needs the
# server to reach the PNPKI responders; off by default for an isolated network.
ESIRA_CHECK_REVOCATION = env_bool("ESIRA_CHECK_REVOCATION", False)
# RFC 3161 time-stamping authority. Empty signs with the server's clock only.
ESIRA_TSA_URL = env("ESIRA_TSA_URL")
ESIRA_SIGNATURE_LOCATION = env(
    "ESIRA_SIGNATURE_LOCATION", "DILG Regional Office XIII - Caraga"
)
ESIRA_MAX_UPLOAD_MB = int(env_float("ESIRA_MAX_UPLOAD_MB", 25))


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
