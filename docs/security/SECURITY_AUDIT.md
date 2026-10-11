# LGMED-IMMS Security Audit

| | |
|---|---|
| System | LGMED-IMMS (DILG Region XIII - Caraga), repository `lgmedimms` |
| Audit date | 2026-10-09 |
| Baseline commit | `ad041fe` (branch `main`) |
| Scope | Application code, configuration, dependencies, repository history, deployment scripts. **Not in scope:** the production server, network, database server and DNS, which were not available for inspection. |
| Method | Manual code review of every app; automated probing of every URL route; `manage.py check --deploy`; `pip-audit`; `bandit`; Git-history secret scan; new regression tests (`core/tests_security.py`). |

Secrets are never reproduced in this report. Where a value matters it is described, not quoted.

---

## 1. System overview

| Area | Finding |
|---|---|
| Language / framework | Python 3.14, Django 6.1.1 |
| Application server | Daphne 4.2 (ASGI) - required, because pages hold a WebSocket (`/ws/live/`, Django Channels 4.3) |
| Database | MySQL / MariaDB via `mysqlclient` (a legacy SQLite file and a JSON export remain on the development machine, untracked) |
| Apps | `accounts`, `core`, `lgus`, `programs` (PPA), `monitoring`, `incoming`, `outgoing`, `datasync`, `services`, `documents`, `announcements`, `reports`, `activities`, `updates`, `administration`, `audit`, `notifications`, `analytics`, `esira` (PNPKI digital signing) |
| Authentication | Django sessions; username + password; TOTP two-step verification (mandatory for System Administrator and Administrator roles, optional for others) with recovery codes; optional reCAPTCHA v3 |
| Authorization | Five roles (System Administrator, Administrator, LGMED Staff, Encoder, Viewer) mapped to capability properties on `User`; `CapabilityRequiredMixin` on views; per-account / per-role module switches (Menu Permissions) enforced by `ModuleAccessMiddleware`; object-level rules in Documents (archive), Activities (ownership/visibility) and e-SIRA (routing) |
| File storage | `MEDIA_ROOT` (`media/`) for most uploads; `PROTECTED_MEDIA_ROOT` (`protected/`) for PPA internal files, profile photos, e-SIRA files, Data Sync workbooks |
| Sensitive data | Personal data of staff and correspondents (RA 10173), incoming/outgoing official correspondence, unpublished reports, PNPKI signing certificates and passphrases (Fernet-encrypted), TOTP secrets, audit trail with IP addresses |
| Outbound connections | Google reCAPTCHA (optional), SMTP (optional), PNPKI OCSP/CRL and TSA (optional) |
| Deployment artefacts at audit time | `run-lan.ps1` (LAN dev server), `run-cloudflare.ps1` (public tunnel to the dev server); no production configuration, no Dockerfile |

### What was already done well

These were verified and are worth preserving:

* Two-step verification is carefully built: pending sign-ins are bound to the password hash, codes cannot be replayed, a per-device lockout counts across sign-ins, recovery codes are hashed, disabling it needs a fresh code, and the Django admin login is redirected to the same flow.
* Views declare a capability and are refused server-side (`core/mixins.py`); hidden buttons are not relied on.
* e-SIRA has a single, well-reasoned permission module (`esira/permissions.py`) consulted by views and the workflow alike.
* PPA internal documents, e-SIRA files and profile photos already live in a protected storage with no URL, served only through authenticated views.
* All database access goes through the ORM; sort fields are allow-listed; no raw SQL, `eval`, shell execution of user input, or unsafe deserialisation was found.
* CSRF middleware is global with no `csrf_exempt` views; logout is POST-only; the session key rotates at sign-in.
* An extensive audit trail records record changes with field-level diffs, sign-ins, failures and denials.
* No real credential was found in the Git history (Section 4).

---

## 2. Findings summary

| ID | Severity | Title | Status |
|---|---|---|---|
| C-01 | CRITICAL | Internal uploaded files publicly reachable at predictable `/media/` URLs | **Fixed** |
| C-02 | CRITICAL | Production configuration fails open (DEBUG on, public fallback SECRET_KEY) | **Fixed** |
| H-01 | HIGH | Administrator can escalate to System Administrator / take over its account | **Fixed** |
| H-02 | HIGH | No brute-force protection on the password step | **Fixed** |
| H-03 | HIGH | Encoders can approve and publish to the public website through record forms | **Fixed** |
| H-04 | HIGH | Unvalidated uploads served inline on the site's origin (stored XSS via HTML/SVG) | **Fixed** |
| M-01 | MEDIUM | Stored XSS via unescaped JSON inside `<script>` (charts) | **Fixed** |
| M-02 | MEDIUM | No Content-Security-Policy | **Fixed** |
| M-03 | MEDIUM | Client IP taken from spoofable `X-Forwarded-For` | **Fixed** |
| M-04 | MEDIUM | Spreadsheet formula injection in CSV/XLSX exports | **Fixed** |
| M-05 | MEDIUM | Dependency manifest incomplete and UTF-16 encoded | **Fixed** |
| M-06 | MEDIUM | TOTP secrets stored in plaintext in the database | Open - recommendation |
| M-07 | MEDIUM | Temporary passwords written to the log when no mail server is configured | Mitigated (deploy check) |
| M-08 | MEDIUM | Development tunnel script exposes a DEBUG server to the internet | Open - procedural |
| M-09 | MEDIUM | No malware scanning of uploaded files | Open - recommendation |
| L-01 | LOW | Open redirects via `next` / `Referer` | **Fixed** |
| L-02 | LOW | Malformed list filters cause HTTP 500 | **Fixed** |
| L-03 | LOW | 500 page fails when the database is down | **Fixed** |
| L-04 | LOW | Cookie and request-size hardening | **Fixed** |
| L-05 | LOW | Database password and TLS not enforced | **Fixed** |
| L-06 | LOW | Minimum password length 8 | **Fixed** (12 for new passwords) |
| L-07 | LOW | CI pipeline could not run the test suite | **Fixed** |
| L-08 | LOW | Project deployment checks never registered (`CoreConfig.ready` not run) | **Fixed** |
| I-01 | INFO | Sensitive files on the development workstation | Action for owner |
| I-02 | INFO | Demonstration password in source (DEBUG-only) | Accepted |
| I-03 | INFO | Django admin reachable at `/django-admin/` | Recommendation |
| I-04 | INFO | HSTS preload not enabled (`security.W021`) | Accepted, documented |
| I-05 | INFO | Jekyll workflow builds the repository as a site | Recommendation |
| I-06 | INFO | Pre-existing failing test unrelated to security | Open |

---

## 3. Findings

### C-01 Internal uploaded files publicly reachable - CRITICAL - Fixed

* **Component:** `config/urls.py` (`static(MEDIA_URL, ...)` in DEBUG), `config/settings.py` (comment directing the production web server to serve `MEDIA_ROOT`), and the `FileField`s of `incoming.IncomingDocument`, `incoming.IncomingUpdate`, `outgoing.OutgoingDocument`, `monitoring.MonitoringAttachment`, `documents.Document`, `documents.DocumentVersion`, `documents.SupportingFile`, `reports.Report`, `updates.UpdateAttachment`, `announcements.Announcement`.
* **Impact:** All of these files sit in `MEDIA_ROOT` under guessable paths (`incoming/2026/09/<original name>`, `documents/2026/<name>`, `documents/versions/<id>/v<n>/<name>`, `reports/<year>/<name>`). Whatever serves `/media/` - the dev server on the LAN or the Cloudflare tunnel today, nginx as the settings comment instructed for production - hands official correspondence, internal reports, unpublished drafts and personal data to anyone, with no sign-in. Templates link to these URLs directly, so a URL seen once (browser history, a forwarded link, a proxy log) stays valid forever. Module switches (Menu Permissions) and the Documents archive restriction are bypassed.
* **Verification:** Before (by code review): `/media/` was mapped to `django.views.static.serve`, which performs no access check, and the settings instructed production to serve the directory directly. After (by test): `MediaGatewayTests.test_internal_attachment_is_refused_to_anonymous_visitors` (404), `test_a_closed_module_closes_its_files_too`, `test_unpublished_report_file_is_not_public`, `test_files_no_record_claims_are_not_served`, `test_path_traversal_is_refused`.
* **Fix:** `core/media.py` - every `/media/` request, in development and production, goes through a view that traces the file to the record(s) storing it and serves it only if (a) the record is released to the public by the same rules the public pages use, or (b) the user is signed in, active, has the module open, and passes the module's record rule (Documents' `visible_to`). Unclaimed paths, traversal attempts and refusals all return 404. `test_every_file_field_in_public_media_is_covered` fails if a new `FileField` in `MEDIA_ROOT` is not registered. The nginx template deliberately has no `/media/` alias. Template URLs did not change.

### C-02 Production configuration fails open - CRITICAL - Fixed

* **Component:** `config/settings.py`.
* **Impact:** `DEBUG` defaulted to **on** when `DJANGO_DEBUG` was absent, and `SECRET_KEY` fell back to a constant committed in the repository. A server started without its environment file (a mistyped path, a service unit missing `EnvironmentFile=`) would run as a debug server that prints settings, SQL and source on any error, signed with a publicly known key - enabling forged sessions and password-reset tokens, and (because the e-SIRA vault key is derived from `SECRET_KEY` when `ESIRA_CREDENTIAL_KEY` is unset) decryption of stored PNPKI certificates and passphrases from a database copy. `ALLOWED_HOSTS` also defaulted to a private IP address.
* **Verification:** `FailClosedSettingsTests` start Django in a subprocess with production settings and missing/weak values and assert it refuses to start; `test_debug_is_off_unless_asked_for`.
* **Fix:** `DEBUG` now defaults to off. With DEBUG off, startup raises `ImproperlyConfigured` when `DJANGO_SECRET_KEY` is missing, is the dev key, starts with `django-insecure`, is under 50 characters or has fewer than 5 distinct characters; when `DJANGO_ALLOWED_HOSTS` is empty or `*`; when `MYSQL_PASSWORD` is empty. The development machine's `venv/lgmed.env` was given `DJANGO_DEBUG=1` so local work is unchanged.

### H-01 Administrator can become System Administrator - HIGH - Fixed

* **Component:** `accounts/forms.py` (`UserForm`), `accounts/views.py` (`UserUpdateView`, `UserPasswordResetView`, `UserActivationView`, `UserMFAResetView`).
* **Impact:** Users & Roles is open to the Administrator role (`can_administer`), but nothing stopped an Administrator from assigning the System Administrator role (to a new account whose temporary password is mailed to an address they choose, or to an existing account), or from resetting a System Administrator's password and two-step verification - a full takeover of the highest-privilege account, including Menu Permissions, which is meant to be System-Administrator-only.
* **Verification:** `RoleEscalationTests` (5 tests): Administrator cannot grant the role, create such an account, or GET/POST edit, password reset, MFA reset or deactivation on a System Administrator (403); System Administrator still can; Administrator still manages ordinary accounts.
* **Fix:** The role choice is removed from the form for non-System-Administrators and rejected in `clean_role`; `_refuse_if_outranked()` returns 403 for any change to a System Administrator's account by someone who is not one.

### H-02 No brute-force protection on the password step - HIGH - Fixed

* **Component:** `accounts/forms.py` (`LoginForm`).
* **Impact:** Unlimited password guesses were possible. reCAPTCHA is optional (and off when keys are absent); two-step verification is mandatory only for administrators, so Staff, Encoder and Viewer accounts were protected by the password alone.
* **Verification:** `LoginThrottleTests` (5 tests): after the limit, even the correct password is refused without being checked; success clears the count; other machines are unaffected; spraying many usernames from one address is throttled; forged `X-Forwarded-For` does not reset the count.
* **Fix:** `accounts/throttle.py` - sliding-window counters in the Django cache per account+address (5 / 15 min), per address (30) and per account (20), checked before reCAPTCHA and before the password hasher. Throttled attempts are written to the audit log. The pause expires by itself (no permanent lockout that a stranger could impose). nginx template adds a request-rate limit on `/accounts/login/` as a second layer.
* **Residual:** with the default in-memory cache, counters are per process and reset on restart (see deployment guide, `lgmed.W003`).

### H-03 Encoders can approve and publish - HIGH - Fixed

* **Component:** `reports` (`status`), `announcements` (`is_published`, `is_featured`), `services` (`is_published`), `monitoring` (`status = COMPLETED`); `core/views_base.py`, `core/forms_base.py`.
* **Impact:** The role definitions state that Encoders "cannot ... approve, publish" and that publishing belongs to `can_approve`. The forms nonetheless accepted those fields from any user with `can_encode`, so an Encoder could put a report or news item on the public website, feature it on the homepage, or mark a report approved, by ticking a box or editing the POST. (Activities already enforced this correctly.)
* **Verification:** `PublicationByEncoderTests` (4 tests).
* **Fix:** `ModuleFormMixin.approval_fields` / `approval_choices`: for users without `can_approve` the publishing fields are removed and approval states withheld; a record already approved keeps its state when an encoder edits it. The restriction is applied inside `GovModelForm.__init__` - the base form validates during construction, so restricting afterwards was ineffective (found by the new tests).

### H-04 Unvalidated uploads served inline - HIGH - Fixed

* **Component:** `incoming/forms.py` (both attachments), `monitoring/forms.py`, `reports/forms.py`; `core/files.py` (`serve_inline`).
* **Impact:** These forms accepted any file type. `serve_inline` returned files inline with a content type guessed from the name, so an uploaded `.html` or `.svg` ran as a page on the system's own origin when a colleague opened it - stored XSS able to act with the Chief's or an administrator's session.
* **Verification:** `UploadValidationTests` (4), `MediaGatewayTests.test_markup_is_never_served_inline`.
* **Fix:** All four forms use the Documents module's allow-list (PDF, Office, common images, CSV) and size limit, plus a new content-signature check (`core/uploads.py`) that rejects a file whose bytes contradict its extension (e.g. HTML renamed `.pdf`). Existing files are not re-validated on edit. Only PDFs and images are ever served inline; everything else is a download as `application/octet-stream`, in both `serve_inline` and the media gateway.

### M-01 Stored XSS via JSON in `<script>` - MEDIUM - Fixed

* **Component:** `core/views.py`, `analytics/views.py`, `updates/views.py` rendering `{{ charts_json|safe }}` inside `<script type="application/json">`.
* **Impact:** `json.dumps` does not escape `<`, so a label containing `</script><script>...` (an office, LGU, type or person name entered by staff) closes the element and runs script on dashboards - including the public Accomplishments page.
* **Fix / verification:** `core/safe_json.py` escapes `<`, `>`, `&` as `<` etc.; `OutputEncodingTests.test_script_json_cannot_close_its_script_element`. CSP (M-02) is a second layer.

### M-02 No Content-Security-Policy - MEDIUM - Fixed

* **Fix:** Django 6.1's built-in `ContentSecurityPolicyMiddleware`: scripts only from self (plus Google for reCAPTCHA) or inline with a per-request nonce; no `unsafe-inline`/`unsafe-eval` for scripts; `object-src 'none'`; `frame-ancestors 'self'`; `form-action 'self'`; `base-uri 'self'`. The 11 inline `<script>` blocks received the nonce; the 17 inline `onclick`/`onchange` handlers were replaced by `data-print`, `data-autosubmit`, `data-set-field` handled in `static/js/app.js`. `DJANGO_CSP_REPORT_ONLY=1` switches to report-only for staging trials.
* **Verification:** `RequestForgeryAndHeaderTests.test_security_headers_on_a_page`, `test_inline_scripts_carry_the_request_nonce`, `TemplateHygieneTests` (no inline handlers; every inline script has the nonce).
* **Not verified:** behaviour in a real browser (no headless browser was available). Exercise the pages listed in the checklist on staging before enforcing in production.

### M-03 Spoofable client IP - MEDIUM - Fixed

* **Component:** `audit/recording.py` (`client_ip`).
* **Impact:** The leftmost `X-Forwarded-For` value - chosen by the client - was recorded in the audit log, and would have let an attacker rotate addresses past an IP-based throttle. An over-long value could also fail the audit insert.
* **Fix / verification:** `X-Forwarded-For` is read only when `DJANGO_TRUST_X_FORWARDED_FOR=1`, and then only its last entry (the one the trusted proxy appended); values are validated as IP addresses. `ClientAddressTests`, `LoginThrottleTests.test_forged_forwarded_for_does_not_reset_the_count`.

### M-04 Formula injection in exports - MEDIUM - Fixed

* **Component:** CSV exports in `core/views_base.py`, `analytics`, `incoming`, `updates`; XLSX report in `datasync/report.py`.
* **Impact:** Cells beginning with `=`, `+`, `-`, `@` run as formulas in Excel (e.g. `=HYPERLINK(...)`). Data Sync re-exports values read from outside spreadsheets.
* **Fix / verification:** `core/csv_safe.py` prefixes such cells with `'` (numbers untouched) via a drop-in `csv.writer`; the XLSX report applies the same. `OutputEncodingTests.test_csv_cells_cannot_become_formulas`.

### M-05 Dependency manifest - MEDIUM - Fixed

* **Impact:** `requirements.txt` was UTF-16 and listed 8 of the 46 installed packages - not `daphne`, `channels`, `pyHanko`, `cryptography` or `Pillow`. A production install would fail or pull unreviewed latest versions.
* **Fix:** Regenerated as UTF-8 with every package pinned to the tested version. `pip-audit -r requirements.txt`: **no known vulnerabilities** (2026-10-09). CI now runs `pip-audit`.

### M-06 TOTP secrets in plaintext - MEDIUM - Open

* **Component:** `accounts.MFADevice.secret`.
* **Impact:** Anyone with a copy of the database (a leaked backup) can generate valid second-factor codes for every enrolled account, reducing two-step verification to the password.
* **Recommendation:** Encrypt the column with a Fernet key held outside the database (the pattern already used by `esira/signing/vault.py`), via a schema migration (the column must grow from 64 characters) and a data migration. Not done here because it needs a key-management decision and a migration that must be rehearsed on a copy of production data. Until then, treat database backups as secrets (encrypted backups - see BACKUP_AND_RECOVERY.md).

### M-07 Temporary passwords in logs without SMTP - MEDIUM - Mitigated

* **Impact:** With no `EMAIL_HOST`, Django's console backend writes every email - including new accounts' temporary passwords - to the server log.
* **Mitigation:** Deployment check `lgmed.W005` warns. **Action:** configure SMTP before creating accounts in production.

### M-08 Development tunnel - MEDIUM - Open (procedural)

* **Component:** `run-cloudflare.ps1`.
* **Impact:** Publishes the DEBUG development server - with demonstration accounts, debug error pages and the development database - to the internet. Combined with C-01 (before the fix) any upload was public.
* **Recommendation:** Use only with demonstration data, stop the tunnel after use, never on a machine holding real records. Consider removing the script from the production branch.

### M-09 No malware scanning - MEDIUM - Open

* **Impact:** Files from LGUs and the public are stored and opened by staff. The new signature check stops disguised files, not malicious PDFs or Office macros.
* **Recommendation:** Scan uploads with ClamAV (`clamd`) on the server or rely on managed endpoint protection on staff PCs; at minimum keep Office's Protected View enabled.

### L-01 Open redirects - LOW - Fixed

`programs/views.py` (4 places) followed `POST next` and `notifications/views.py` followed `Referer` without checking the host. CSRF limits exploitation to same-site posts, hence LOW. Fixed with `core/redirects.safe_next` (also applied to stored notification URLs). Tests: `test_open_redirects_are_refused`, `RefererRedirectTests`.

### L-02 Malformed filters cause 500 - LOW - Fixed

`?document_type=abc` or `?from=not-a-date` raised inside the ORM. Invalid values are now ignored (`core/views_base._filter_or_ignore`). Test: `MalformedQueryTests`.

### L-03 500 page depends on the database - LOW - Fixed

The branded error page runs context processors that query the database. `core/errors.server_error` falls back to a static page with no detail. Test: `SafeErrorTests`.

### L-04 Cookie and request hardening - LOW - Fixed

Added `CSRF_COOKIE_HTTPONLY`, explicit `SameSite=Lax`, `__Host-` cookie names in production, `Cross-Origin-Opener-Policy`, `DATA_UPLOAD_MAX_*` limits, restrictive upload file permissions, configurable HSTS (start low, raise after verification), production logging to the console without request bodies. JavaScript reads the CSRF token from the form, not the cookie (verified).

### L-05 Database credentials and transport - LOW - Fixed

Production refuses to start without `MYSQL_PASSWORD`; `MYSQL_SSL_CA` enables verified TLS to a remote database server.

### L-06 Password length - LOW - Fixed

Minimum length 12 (configurable) for passwords set from now on; existing passwords keep working until changed.

### L-07 CI could not test - LOW - Fixed

The workflow targeted Python 3.9-3.11 (Django 6.1 needs 3.12+) and ran `pytest`, which does not discover these Django tests. Replaced with: MySQL service, `check`, `check --deploy` with production settings, missing-migration check, full test suite, `pip-audit`.

### L-08 Project checks not registered - LOW - Fixed

`core/apps.py` contains two `AppConfig` classes, so Django did not select `CoreConfig` automatically and its `ready()` never ran. Marked `default = True`; the new `lgmed.W001`-`W005` deployment checks now appear in `check --deploy`.

### I-01 Sensitive files on the development workstation - INFO

`acounts.txt` (demonstration passwords in plain text), `db.sqlite3` and `db-export.json` (user records and audit trail) and `venv/lgmed.env` (live reCAPTCHA, SMTP, MySQL and secret keys) exist in the working copy. All are git-ignored and **none appears anywhere in the Git history** (verified). Recommend deleting the SQLite file and JSON export once the MySQL migration is confirmed, and keeping the workstation disk encrypted (BitLocker). `venv/lgmed.env` currently sets `LGMED_MFA_OFF=1`; it has effect only in DEBUG, but should be removed.

### I-02 Demonstration password in source - INFO - Accepted

`bootstrap_demo` and the README contain the demonstration accounts' password. The command refuses to run with DEBUG off. Ensure no production account was ever created with it.

### I-03 Django admin - INFO

`/django-admin/` is reachable but behind the same sign-in and two-step verification, and only for `is_staff` accounts. It bypasses some form-level workflow rules; the nginx template shows how to restrict it to the office network.

### I-04 HSTS preload - INFO - Accepted

Preloading binds the whole parent domain and is the domain owner's decision; `security.W021` is silenced with that rationale and can be enabled with `DJANGO_HSTS_PRELOAD=1`.

### I-05 Jekyll workflow - INFO

`.github/workflows/jekyll-docker.yml` builds the repository as a Jekyll site with `chmod -R 777`. It deploys nothing, but if GitHub Pages is ever enabled the repository's documentation would be published. Remove if unused.

### I-06 Pre-existing failing test - INFO

`programs.tests.PublicationAuthorityTests.test_a_memorandum_not_yet_in_effect_cannot_authorise_a_release` fails on the untouched baseline (before any change in this audit). It concerns PPA publication-date logic and should be investigated separately.

---

## 4. Repository secret scan

* Every file ever added to history was listed and all patches were searched for secret-like assignments, private-key headers and API-key formats.
* **Result:** no real credential, key or certificate in history. Matches were test fixtures (`test-password-1`, `secret-key-for-tests`), the DEBUG-only demonstration password (I-02) and the DEBUG-only development `SECRET_KEY` placeholder (now refused in production).
* `.gitignore` now also excludes `.env.*` (except `.env.example`), `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.crt`, `*.cer`, SQL dumps and `backups/`.

## 5. Automated tool results (2026-10-09)

| Tool | Result |
|---|---|
| `pip-audit -r requirements.txt` | No known vulnerabilities in 46 pinned packages |
| `bandit` (application code, tests excluded) | 0 High. Medium: 3x `mark_safe` (constant SVG icons and the QR code - reviewed, safe), 1x `urlopen` (constant reCAPTCHA HTTPS URL - safe). Low: `random` in demo seeding, fixed-argument `git` subprocess, DEBUG-only constants - all false positives |
| `manage.py check --deploy` (production env) | No Django security warnings; project warnings `lgmed.W001` (no `ESIRA_CREDENTIAL_KEY` locally) and `lgmed.W003` (per-process cache) are configuration items for the server |
| URL probe (`AnonymousAccessTests`) | Every route except the public website, PWA files and sign-in refuses anonymous GET and POST |

See SECURITY_FIXES.md for the change list and test results.
