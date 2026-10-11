"""
Django settings for LGMED-IMMS.

Local Government Monitoring and Evaluation Division -
Information Management and Monitoring System
DILG Regional Office XIII - Caraga
"""

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .env import env, env_bool, env_float, env_int, env_list, load_venv_env, local_ipv4_addresses
from .version import system_version

BASE_DIR = Path(__file__).resolve().parent.parent

# Tops the environment up from <venv>/lgmed.env before anything below reads it,
# so secrets stay out of this file and out of the repository. Real environment
# variables are never overwritten. See config/env.py.
load_venv_env()

# `manage.py test` builds its own throw-away database and never serves anyone,
# so it is excused from the production requirements below. Nothing else is.
RUNNING_TESTS = sys.argv[1:2] == ["test"]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

# Off unless asked for. A server that starts without its environment - a
# missing lgmed.env, a service unit that forgot EnvironmentFile= - must come up
# as a production server that refuses to start, never as a debug server that
# prints settings and source code to anyone who triggers an error. Development
# machines set DJANGO_DEBUG=1 in <venv>/lgmed.env.
DEBUG = env_bool("DJANGO_DEBUG", False)

_DEV_SECRET_KEY = "django-insecure-dev-only-key-replace-before-deployment"
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not (DEBUG or RUNNING_TESTS):
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set. A production server refuses to start "
            "without one - see docs/security/PRODUCTION_DEPLOYMENT.md."
        )
    SECRET_KEY = _DEV_SECRET_KEY
elif not DEBUG and (
    SECRET_KEY == _DEV_SECRET_KEY
    or SECRET_KEY.startswith("django-insecure")
    or len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is too weak for production: use at least 50 random "
        "characters (see docs/security/PRODUCTION_DEPLOYMENT.md)."
    )

# Names this server answers to. Development falls back to the loopback names;
# production must say, because accepting any Host header is what lets a forged
# one poison password-reset links and cached pages.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
if not ALLOWED_HOSTS and not RUNNING_TESTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS is not set. Name the server's own hostname(s), "
        "comma-separated."
    )
if "*" in ALLOWED_HOSTS and not DEBUG:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS may not contain '*' in production.")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


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
    # LGMED-IMMS
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
    # Content-Security-Policy on every response, with a fresh nonce per
    # request for the few inline scripts the templates carry. See SECURE_CSP.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
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
                # {{ csp_nonce }} for inline <script nonce="...">.
                "django.template.context_processors.csp",
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

# A database on another machine is reached over TLS: set MYSQL_SSL_CA to the
# CA certificate that signed the MySQL server's certificate. A database on the
# same host as the application (127.0.0.1 / a socket) does not need it.
if env("MYSQL_SSL_CA"):
    DATABASES["default"]["OPTIONS"]["ssl"] = {"ca": env("MYSQL_SSL_CA")}
    DATABASES["default"]["OPTIONS"]["ssl_mode"] = "VERIFY_IDENTITY"

if not (DEBUG or RUNNING_TESTS) and not DATABASES["default"]["PASSWORD"]:
    raise ImproperlyConfigured(
        "MYSQL_PASSWORD is not set. Production connects with a dedicated, "
        "password-protected database account."
    )

# Shared state for the sign-in throttle (accounts/throttle.py) and the small
# settings cache. In memory is right for the single server process the system
# runs as; several processes must share one, or each keeps its own count of
# failed sign-ins: set DJANGO_CACHE_LOCATION to a Redis URL (needs the `redis`
# package), or to "database" and run `manage.py createcachetable`.
_cache_location = env("DJANGO_CACHE_LOCATION")
if _cache_location.startswith(("redis://", "rediss://")):
    CACHES = {"default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _cache_location,
    }}
elif _cache_location == "database":
    CACHES = {"default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "lgmed_cache",
    }}
else:
    CACHES = {"default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "lgmed-imms",
    }}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    # Twelve characters rather than Django's eight: these accounts hold
    # personal data under RA 10173. Applies to passwords set from now on;
    # existing passwords keep working until they are next changed.
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": env_int("LGMED_PASSWORD_MIN_LENGTH", 12)},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Failed sign-ins tolerated before the password step is paused
# (accounts/throttle.py). Counted per account-and-address, per address and per
# account, over a sliding window; the pause lifts on its own, so a stranger
# cannot lock a colleague out for longer than LOGIN_THROTTLE_WINDOW.
LOGIN_THROTTLE_WINDOW = env_int("LGMED_LOGIN_THROTTLE_WINDOW", 15 * 60)
LOGIN_THROTTLE_PER_USER_IP = env_int("LGMED_LOGIN_THROTTLE_PER_USER_IP", 5)
LOGIN_THROTTLE_PER_IP = env_int("LGMED_LOGIN_THROTTLE_PER_IP", 30)
LOGIN_THROTTLE_PER_USER = env_int("LGMED_LOGIN_THROTTLE_PER_USER", 20)

# Whether to believe X-Forwarded-For for the client's address (audit log,
# sign-in throttle). Only behind a reverse proxy that *appends* the real peer
# address, as Nginx's $proxy_add_x_forwarded_for does: the last entry is then
# the one the proxy itself saw. Without a proxy the header is whatever the
# client typed, so it is ignored.
TRUST_X_FORWARDED_FOR = env_bool("DJANGO_TRUST_X_FORWARDED_FOR", False)

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
    f"LGMED-IMMS <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "LGMED-IMMS <noreply@localhost>"
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
# MEDIA_ROOT holds files the public website shows *and* internal papers, under
# guessable paths. So no web server may map it: every /media/ request goes to
# core/media.py, which traces the file to its record and checks who is asking.
# Still, it is the less guarded of the two roots, and anything released to the
# public is copied here.
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
#   "pkcs12"   Signing with the signer's PNPKI certificate file (.p12/.pfx).
#              The signer either keeps the file and its passphrase on file
#              (encrypted with ESIRA_CREDENTIAL_KEY, see esira/signing/vault.py)
#              or presents them at the moment of signing. The opened key is
#              held in memory for that one request only. This is how PNPKI
#              individual certificates are issued.
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
# Fernet key that encrypts the certificate files and passphrases signers keep
# on file. Empty derives one from SECRET_KEY - then rotating SECRET_KEY makes
# every stored certificate unreadable. Set it in production, keep it out of
# the database backups, and back it up separately.
ESIRA_CREDENTIAL_KEY = env("ESIRA_CREDENTIAL_KEY")
# Written after the time in each signature box ("Date: 2026.10.08 15:04:32 PST").
# PST is Philippine Standard Time, Asia/Manila (TIME_ZONE above).
ESIRA_TIME_ZONE_LABEL = env("ESIRA_TIME_ZONE_LABEL", "PST")


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
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Cookies. The session cookie is never readable from JavaScript; the CSRF
# cookie is not either - the pages read the token from the form or the
# csrfmiddlewaretoken input, never from document.cookie.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
# Prefixed names in production: a "__Host-" cookie is only accepted when set
# over HTTPS, for the exact host and path "/", which stops a sibling
# subdomain from planting a session or CSRF cookie of its own.
if not DEBUG:
    SESSION_COOKIE_NAME = "__Host-sessionid"
    CSRF_COOKIE_NAME = "__Host-csrftoken"

# Request limits. Uploads stream to disk past 2.5 MB, so this bounds the
# non-file part of a request (form fields), not the files themselves - those
# are capped by each form and by the reverse proxy's client_max_body_size.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000
DATA_UPLOAD_MAX_NUMBER_FILES = 100
# Uploaded files never become executable on the server.
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

# Content-Security-Policy (Django's built-in middleware, above). Scripts run
# only from this site, or inline when they carry the request's nonce; nothing
# may frame the site but itself; forms post only here. Google is allowed for
# reCAPTCHA on the sign-in page and nothing else. Inline style attributes stay
# allowed - the templates use them for layout, and a style cannot run code.
#
# DJANGO_CSP_REPORT_ONLY=1 sends the same policy as report-only (the browser
# logs violations in its console but blocks nothing) - for trying a change on
# staging, never as the permanent setting.
from django.utils.csp import CSP  # noqa: E402

_GOOGLE = ["https://www.google.com", "https://www.gstatic.com", "https://recaptcha.google.com"]
_CSP_POLICY = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE, *_GOOGLE],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:", "blob:", *_GOOGLE],
    "font-src": [CSP.SELF, "data:"],
    "connect-src": [CSP.SELF, *_GOOGLE],
    "frame-src": [CSP.SELF, *_GOOGLE],
    "worker-src": [CSP.SELF, "blob:"],
    "manifest-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.SELF],
}
if env_bool("DJANGO_CSP_REPORT_ONLY", False):
    SECURE_CSP_REPORT_ONLY = _CSP_POLICY
else:
    SECURE_CSP = _CSP_POLICY

# Logging. Errors go to the console (journald / the service's log file) in a
# form an administrator can act on; nothing here writes request bodies,
# passwords or cookies. Django's own error reporting already scrubs settings
# and POST values whose names look sensitive.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO"), "propagate": False},
        # A forged Host header is noise from scanners, not an incident.
        "django.security.DisallowedHost": {"handlers": [], "propagate": False},
    },
}

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)

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
    if env_bool("DJANGO_BEHIND_TLS_PROXY", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # A year, once HTTPS is known to work on every name the site answers to.
    # Start lower (e.g. 3600) on a first deployment: a browser that has seen
    # this header refuses plain HTTP to the site until it expires.
    SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
    # Preload is a commitment for the whole domain (dilg.gov.ph and every
    # subdomain), made by the domain's owner - not something this application
    # can decide. security.W021 is therefore expected and silenced.
    if not SECURE_HSTS_PRELOAD:
        SILENCED_SYSTEM_CHECKS = ["security.W021"]
