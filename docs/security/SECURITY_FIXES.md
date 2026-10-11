# LGMED-IMMS Security Fixes

Changes made on 2026-10-09 against baseline commit `ad041fe`. Finding IDs refer to [SECURITY_AUDIT.md](SECURITY_AUDIT.md). Business logic, workflows, URLs and the interface were kept as they were except where a change was the fix itself; each such case is called out under **Behaviour change**.

## 1. Changes by finding

### C-01 - Media gateway

| File | Change |
|---|---|
| `core/media.py` (new) | `serve()` view and `SOURCES` registry: traces a `/media/` path to the record(s) storing it; serves to the public only what the public pages already release; serves to staff by module access and record rules; 404 for everything else; PDFs/images inline, all else as download; `Cache-Control: private` and `noindex` for internal files |
| `config/urls.py` | `/media/<path>` routed to the gateway in all modes; DEBUG-only `static()` serving removed |
| `deploy/nginx/lgmed-imms.conf` | No `/media/` alias (comment explains why) |

**Behaviour change:** a file in `media/` that no record references is no longer downloadable (it was an orphan). Anonymous visitors still get every file the public website shows.

### C-02 - Fail-closed settings

| File | Change |
|---|---|
| `config/settings.py` | `DEBUG` defaults to off; production refuses to start without a strong `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS` (no `*`), and `MYSQL_PASSWORD`; `RUNNING_TESTS` exemption for `manage.py test` only |
| `config/env.py` | `env_int()` helper |
| `venv/lgmed.env` (local, untracked) | `DJANGO_DEBUG=1` added so the development machine keeps working |

**Behaviour change:** any machine that relied on the implicit DEBUG default must now set `DJANGO_DEBUG=1`.

### H-01 - Role escalation

| File | Change |
|---|---|
| `accounts/forms.py` | `UserForm` hides the System Administrator role from non-System-Administrators and rejects it in `clean_role` |
| `accounts/views.py` | `_refuse_if_outranked()` in edit, password reset (GET and POST), activation and MFA reset |

**Behaviour change:** Administrators can no longer create, edit, reset or deactivate System Administrator accounts; a System Administrator must.

### H-02 - Sign-in throttle

| File | Change |
|---|---|
| `accounts/throttle.py` (new) | Sliding-window failure counters (account+address, address, account) in the Django cache |
| `accounts/forms.py` | `LoginForm.clean` checks the throttle first, records failures/successes, logs throttled attempts to the audit trail |
| `config/settings.py` | `LOGIN_THROTTLE_*` (env-configurable), `CACHES` (memory / Redis / database via `DJANGO_CACHE_LOCATION`) |

**Behaviour change:** after 5 wrong passwords for one account from one address within 15 minutes, sign-in pauses until the window passes, with a message saying how long.

### H-03 - Approval and publication by role

| File | Change |
|---|---|
| `core/views_base.py` | `ModuleFormMixin.approval_fields` / `approval_choices` and `restrict_to_non_approver()` passed to the form |
| `core/forms_base.py` | `GovModelForm` accepts `restrict_fields` and applies it before first validation |
| `reports/views.py` | Approved/Published statuses reserved for approvers |
| `announcements/views.py` | `is_published`, `is_featured` reserved for approvers |
| `services/views.py` | `is_published` reserved for approvers |
| `monitoring/views.py` | Completed status reserved for approvers |

**Behaviour change:** Encoders no longer see these fields/choices. This implements the documented role policy (`accounts/capabilities.py`).

### H-04 - Upload validation and safe serving

| File | Change |
|---|---|
| `core/uploads.py` (new) | Content-signature check for PDF, Office (OLE/OOXML), JPEG, PNG, GIF, WebP, BMP, TIFF; CSV/TXT must not be binary or markup |
| `documents/forms.py` | `validate_upload` judges only new uploads and adds the signature check |
| `incoming/forms.py`, `monitoring/forms.py`, `reports/forms.py` | Attachments validated with the Documents allow-list and size limit; `accept` attribute and format help added |
| `core/files.py` | `serve_inline` serves only PDF/images inline; everything else as an `application/octet-stream` download |

**Behaviour change:** these modules now refuse file types outside PDF/Office/images/CSV and files whose content does not match their extension.

### Medium and low findings

| ID | Files | Change |
|---|---|---|
| M-01 | `core/safe_json.py` (new); `core/views.py`, `analytics/views.py`, `updates/views.py` | Chart JSON escaped for `<script>` context |
| M-02 | `config/settings.py`; 11 templates (nonce); 16 templates (handlers); `static/js/app.js` | CSP middleware with nonces; inline handlers replaced by `data-print`, `data-autosubmit`, `data-set-field`/`data-set-value` |
| M-03 | `audit/recording.py`; `config/settings.py` | `client_ip` trusts `X-Forwarded-For` only with `DJANGO_TRUST_X_FORWARDED_FOR=1`, uses the last hop, validates the address |
| M-04 | `core/csv_safe.py` (new); `core/views_base.py`, `analytics/views.py`, `incoming/views.py`, `updates/views.py`, `datasync/report.py` | Formula-trigger cells prefixed with `'` |
| M-05 | `requirements.txt` | UTF-8, all 46 packages pinned |
| M-07 | `core/checks.py` (new), `core/apps.py` | Deployment checks `lgmed.W001`-`W005` |
| L-01 | `core/redirects.py` (new); `programs/views.py`, `notifications/views.py` | `safe_next()` for `next`, `Referer` and stored notification URLs |
| L-02 | `core/views_base.py` | Invalid filter/date values ignored |
| L-03 | `core/errors.py` | Static fallback 500 page |
| L-04 | `config/settings.py` | Cookie flags and `__Host-` names, COOP, upload limits/permissions, HSTS env settings, logging |
| L-05 | `config/settings.py` | `MYSQL_SSL_CA` → verified TLS |
| L-06 | `config/settings.py` | Minimum password length 12 |
| L-07 | `.github/workflows/python-package.yml` | Real CI: MySQL, checks, migrations, tests, `pip-audit` |
| L-08 | `core/apps.py` | `CoreConfig.default = True` |

### Configuration and documentation added

| File | Purpose |
|---|---|
| `.env.example` | Every environment variable, placeholders only, with generation commands |
| `.gitignore` | Keys, certificates, `.env.*`, dumps, backups |
| `deploy/nginx/lgmed-imms.conf`, `deploy/nginx/lgmed-imms-proxy.conf` | TLS reverse proxy template |
| `deploy/systemd/lgmed-imms.service` | Sandboxed Daphne service template |
| `deploy/backup/lgmed-backup.sh` | Encrypted nightly backup template |
| `docs/security/*.md` | This document set |
| `core/tests_security.py` | 51 security regression tests |

## 2. Test results

All runs on the development machine (Windows 11, Python 3.14.7, MySQL test database), 2026-10-09.

| Run | Result |
|---|---|
| Baseline, before any change | 766 tests: 765 passed, **1 failed** (pre-existing, I-06) |
| `core.tests_security` | 51 tests: all PASSED |
| Full suite after the changes | 816 tests: 815 passed, 1 failed - the same pre-existing failure (I-06), no regressions |
| Re-run of `core`, `accounts`, `incoming`, `monitoring`, `reports`, `announcements`, `services`, `documents` on the final code | 342 tests: all PASSED |
| `manage.py check` | No issues |
| `manage.py check --deploy` (production environment variables) | No Django warnings; `lgmed.W001`, `lgmed.W003` (server configuration items) |
| `manage.py makemigrations --check` | No changes - no migration is required by these fixes |
| `pip-audit -r requirements.txt` | No known vulnerabilities |
| `bandit` | No actionable findings (see audit §5) |

## 3. Security test inventory

| Area | Test class | Status |
|---|---|---|
| Unauthenticated access to every route (GET + POST) | `AnonymousAccessTests` | PASSED |
| Media gateway: anonymous, staff, closed module, publication state, orphan files, traversal, markup, registry completeness | `MediaGatewayTests` | PASSED |
| Authentication throttling | `LoginThrottleTests` | PASSED |
| Spoofed client address | `ClientAddressTests` | PASSED |
| Privilege escalation between roles | `RoleEscalationTests` | PASSED |
| Mass assignment / publication by role | `PublicationByEncoderTests` | PASSED |
| CSRF enforcement, security headers, CSP nonce, cookie flags, session rotation, session invalidation on password change, POST-only logout | `RequestForgeryAndHeaderTests` | PASSED |
| No inline handlers; nonce on inline scripts | `TemplateHygieneTests` | PASSED |
| Script-context JSON, CSV formulas, open redirects | `OutputEncodingTests`, `RefererRedirectTests` | PASSED |
| Malicious / mislabelled uploads | `UploadValidationTests` | PASSED |
| Malformed query strings | `MalformedQueryTests` | PASSED |
| Safe error page | `SafeErrorTests` | PASSED |
| Fail-closed production settings | `FailClosedSettingsTests` | PASSED |
| CSP in a real browser | - | NOT RUN (no headless browser available) |
| TLS, headers and redirects on the production host | - | BLOCKED (no production environment) |
| Backup restore drill | - | NOT RUN (procedure documented) |

Existing tests that already covered IDOR and role rules (Documents archive visibility, Activities ownership, e-SIRA routing, Incoming assignment, PPA review) continue to pass as part of the full suite.
