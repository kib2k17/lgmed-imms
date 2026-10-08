"""
Settings for the throw-away instance the user manual's screenshots are taken from.

    set DJANGO_SETTINGS_MODULE=docs_settings
    set PYTHONPATH=docs\\manual\\build

It is the real configuration with four things moved out of harm's way, so the
screenshots show the real interface without touching the office's database:

- the database is a fresh SQLite file under LGDOCS_WORKDIR (default C:\\lgdt),
  seeded only with the project's own demonstration data (seed_lgus,
  bootstrap_demo, seed_records) - never with live records;
- uploaded and protected files are written beside it, not into media/ or
  protected/ in the working copy;
- e-mail goes to memory, so creating an account during capture mails nobody;
- the sign-in reCAPTCHA and the two-step code are off (DEBUG only), so the
  capture script can sign in as each demonstration role.

Never point this at a deployed system.
"""

import os
from pathlib import Path

from config.settings import *  # noqa: F401,F403
from config.settings import DEBUG

if not DEBUG:
    raise RuntimeError("docs_settings is for the documentation instance only (DEBUG must be on).")

WORKDIR = Path(os.environ.get("LGDOCS_WORKDIR", r"C:\lgdt"))
WORKDIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": WORKDIR / "manual-docs.sqlite3",
        "OPTIONS": {"timeout": 30},
    }
}

MEDIA_ROOT = WORKDIR / "media"
PROTECTED_MEDIA_ROOT = WORKDIR / "protected"

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
ACCOUNT_NOTIFY_EMAILS = []

RECAPTCHA_SITE_KEY = ""
RECAPTCHA_SECRET_KEY = ""
MFA_OFF = True

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
