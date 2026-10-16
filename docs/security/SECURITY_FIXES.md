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

## 4. Improvement plan, Phases 0 and 1 (2026-10-16)

Task IDs refer to the LGMED-IMMS Phased Improvement Plan of 2026-10-16.

### Phase 0 - housekeeping

| Task | File | Change |
|---|---|---|
| 0.1 | `programs/tests.py` | `TODAY` is the real date; a fixed date had aged out and failed the not-yet-in-effect test (I-06) |
| 0.2 | `venv/lgmed.env` (local, untracked) | `LGMED_MFA_OFF` commented out |
| 0.3 | `tunnel-guard.ps1` (new), `run-ngrok.ps1`, `run-cloudflare.ps1`, `docs/demo-tunnel.md` | Tunnels refuse the real database and `LGMED_MFA_OFF`; `-Serve` starts the server on a `_demo` database with MFA on (M-08) |
| 0.4 | `.github/workflows/jekyll-docker.yml` | Removed (I-05) |

### Phase 1 - account and signing security

| Task | File | Change |
|---|---|---|
| 1.1 | `accounts/models.py`, migration `accounts.0007` | `User.must_change_password`, set on account creation and administrator reset |
| 1.2 | `accounts/middleware.py`, `config/settings.py` | `PasswordChangeRequiredMiddleware` holds a flagged account on the change page; background requests get 403 |
| 1.3 | `accounts/views.py`, `accounts/forms.py`, `accounts/urls.py`, `templates/accounts/password_change.html`, `templates/accounts/profile.html`, `audit/models.py`, migration `audit.0007` | Self-service password change from My Profile; `PASSWORD_CHANGED` audit action; other sessions signed out |
| 1.4 | `accounts/forms.py`, `accounts/views.py`, `accounts/emails.py`, `templates/dashboard/users/password.html`, `templates/emails/password_reset.*` | Administrator reset generates the password and emails it; shown once, uncached, only if the email fails |
| 1.5 | `esira/workflow.py`, `esira/views.py`, `templates/dashboard/esira/certificates.html` | The passphrase prompt cannot be switched off without MFA; a signer without MFA is always asked |
| 1.6 | `accounts/models.py` | `mfa_required` covers `can_approve` (LGMED Staff) and holders of a verified, unexpired signing certificate (decision D1: no grace period) |
| 1.7 | `esira/workflow.py` | No superuser exemption from verifying one's own certificate |
| 1.7 | `accounts/views.py` | Reset page looks the account up only after the sign-in and capability checks (no ID enumeration) |
| 1.7 | `core/views.py` | Public PPA files: only PDFs and pictures inline, everything else a download |
| 1.7 | `datasync/views.py` | Batch preview requires the profile's capability |
| 1.7 | `accounts/throttle.py` | Failures counted in atomic per-bucket counters instead of a read-modify-write list |
| 1.9 | `esira/views.py`, `static/js/esira-certificates.js`, `templates/dashboard/esira/certificates.html` | "Show my certificate password" requires a current two-step code (shared lockout; failures audit-logged as ACCESS_DENIED); unavailable without two-step verification. Found during Phase 1, outside the original plan |
| 1.8 | `core/checks.py`, `.github/workflows/python-package.yml`, `docs/security/PRODUCTION_DEPLOYMENT.md` | Missing `ESIRA_CREDENTIAL_KEY` is an error (`lgmed.E001`) when DEBUG is off; CI uses a throw-away key |

**Behaviour changes:** LGMED Staff, and anyone with a verified signing certificate, must enrol an authenticator at their next sign-in. New and reset accounts must choose a password before using the system. Administrators no longer type a password when resetting one. A production server without `ESIRA_CREDENTIAL_KEY` fails `check --deploy`.

Tests: `accounts/test_password.py` (new), plus additions to `accounts/tests.py`, `accounts/test_mfa.py`, `esira/tests.py`, `datasync/tests.py` and `programs/tests.py`.

## 5. Improvement plan, Phase 2 - data protection (2026-10-16)

| Task | File | Change |
|---|---|---|
| 2.1 | `accounts/vault.py` (new), `accounts/models.py`, `accounts/mfa.py`, migration `accounts.0008`, `config/settings.py`, `.env.example`, `core/checks.py` | Authenticator secrets stored as Fernet tokens under `LGMED_MFA_KEY` (derived from `SECRET_KEY` when unset; `lgmed.W006` warns). The migration widens the column, seals existing secrets, and reverses cleanly. A secret that cannot be decrypted refuses app codes but still accepts recovery codes (M-06) |
| 2.2 | `accounts/test_mfa.py` | Rehearsed on the test database: sealing, idempotence, unsealing, legacy plain-text rows, changed key |
| 2.3 | `accounts/views.py`, `templates/dashboard/users/password.html` | **Changed from the plan.** Account emails are *not* queued in a database outbox: they carry a temporary password, which a queue would store until sent. A failed welcome email now shows the password once (uncached) to the administrator, as a failed reset email already does |
| 2.4 | `documents/upload_rules.py` (new), `documents/models.py`, `documents/forms.py`, `incoming/models.py`, `outgoing/models.py`, `monitoring/models.py`, `reports/models.py`, migrations (no SQL) | The upload rules also run as model-field validators, so a Django-admin upload meets them; only newly posted files are judged |
| 2.5 | `core/antivirus.py` (new), `core/middleware.py`, `config/settings.py`, `.env.example`, `core/checks.py` | Optional ClamAV scanning of every uploaded file before any view runs, over the clamd INSTREAM protocol (no new package). Off unless `LGMED_CLAMAV_ADDRESS` is set (`lgmed.W007` warns); infected files refused with 422 and audit-logged; scanner outage logs and passes, or refuses with 503 when `LGMED_CLAMAV_REQUIRED=1` (M-09, decision D3 still open) |

**Behaviour changes:** after `migrate`, two-step verification keeps working for every enrolled account; rotating `SECRET_KEY` without `LGMED_MFA_KEY` set now also requires re-enrolment. A failed welcome email shows the temporary password on screen instead of asking for a separate reset.

Tests: `core/tests_antivirus.py` (new, fake clamd), `accounts/test_mfa.py` (`SecretEncryptionTests`), `documents/tests.py` (`ModelLevelUploadValidationTests`), `accounts/tests.py`.

## 6. Improvement plan, Phase 3 - performance (2026-10-16)

### 3.0 Measurements

Taken on the test database by `core/tests_performance.py` (`PRINT_FIGURES = True`), before on commit `1fb623c`, after on this branch, each after one warm-up request. 5,000 audit rows for the export.

| Request | Before | After |
|---|---|---|
| Dashboard | 36 queries, 99 ms | 8 queries, 50-69 ms |
| Internal file late in the media gateway's list (Outgoing) | 16 queries, 62 ms | 9 queries, 22 ms |
| Public announcement image (first in the list) | 2 queries | 2 queries |
| Audit log page | 20 queries, 326 ms | 16 queries, 248-303 ms |
| Audit CSV export | 11 queries, 1.7 s, 12.4 MiB peak (Python heap) | one query per 1,000 rows, 1.5-2.7 s, 6.3 MiB, streamed |

Correction to the audit report: the media gateway's cost was not "11 queries per file" for every file. It stopped at the first public owner, so announcement images were already cheap; the cost fell on files owned by models late in `SOURCES` and on refused requests.

### Changes

| Task | File | Change |
|---|---|---|
| 3.1 | `core/media.py` | `PREFIX_SOURCES`: a path's prefix names the models that can own it (including the register's copies of Incoming/Outgoing files); those are asked first, and every other source is still asked before a request is refused - so no access decision changed |
| 3.2 | `core/files.py`, `core/media.py`, `documents/views.py`, `submissions/views.py`, `programs/views.py`, `config/settings.py`, `deploy/nginx/lgmed-imms.conf` | `send_stored` / `send_fieldfile`: with `LGMED_ACCEL_REDIRECT=1`, after the access check Django answers with `X-Accel-Redirect` to an `internal` nginx location, which sets the security headers nginx does not carry over. Off by default. e-SIRA PDFs are excluded: they are verified against their SHA-256 in memory before serving |
| 3.3 | `core/views.py`, `config/settings.py` | Office-wide dashboard figures cached for `LGMED_DASHBOARD_CACHE_SECONDS` (60; 0 under tests); the page's "Figures as of" shows when; upcoming activities stay per user |
| 3.4 | `core/views_base.py`, `audit/views.py` | CSV export streamed, read 1,000 rows at a time by key (the MySQL driver otherwise buffers the whole result), related rows joined from the export columns, row count audited before the first byte; the audit log's filter lists computed once per request instead of three times |
| 3.5 | - | Not done: Outgoing is filtered by `date_sent` (indexed) and quick views; `communication_type` is only a sort column |

Tests: `core/tests_performance.py` (new) holds query budgets for each request above and the accel-redirect behaviour; `activities/tests.py` and `monitoring/tests.py` read the export as a stream.

## 7. Improvement plan, Phase 4 - user experience (2026-10-16)

| Task | File | Change |
|---|---|---|
| 4.1 | `core/stats.py`, `core/views.py`, `templates/dashboard/dashboard.html` | Office-wide figures are tagged with their module and narrowed per viewer (`for_viewer`): a module closed in Menu Permissions shows no card, chart, count, panel or action button, and the Chief's incoming review queue and monitoring review appear only to the roles that act on them. New "My Work" panel (`my_work`, never cached): incoming documents to acknowledge and assigned to the viewer (one aggregate query), register documents assigned to them, e-SIRA documents waiting on them, and their missing MMIA/DTR for the open month |
| 4.2 | `static/css/app.src.css`, `templates/dashboard/module_list.html`, `templates/dashboard/incoming/list.html`, `templates/dashboard/documents/list.html`, `templates/dashboard/activities/calendar.html` | `table-stack`: below 640 px a list row becomes a card, each cell labelled from `data-label`; the received/due dates stay visible (`stack-show`). The month grid gives way to the month's list on phones |
| 4.3 | `core/consumers.py`, `notifications/service.py`, `static/js/app.js`, `static/js/pwa.js` | A new notification sends the recipient's open pages a bare "check now" over the existing WebSocket (per-user group, after commit); the page then asks the session-checked status endpoint. No notification content crosses the socket. The fallback poll slows from 1 to 5 minutes while the socket is up |
| 4.4 | `templates/components/chart_card.html`, `static/js/app.js`, `static/js/analytics.js`, `static/js/updates.js`, `static/css/app.src.css` | Chart placeholders while the charting script loads; removed when charts are drawn or cannot be; hidden without JavaScript; the pulse respects reduced motion |
| 4.5 | `notifications/views.py`, `notifications/urls.py`, `templates/dashboard/notifications/list.html`, `incoming/views.py`, `incoming/urls.py`, `templates/dashboard/incoming/list.html`, `static/js/app.js` | Bulk mark-read / dismiss for one's own notifications; bulk acknowledge of one's own incoming assignments, each through `workflow.acknowledge` and its permission check, with a confirmation (`data-confirm-submit`). Bulk assign and bulk archive were not built: each needs a per-document decision (due date, retention) |
| 4.6 | `core/management/commands/build_dark_css.py` (new), `static/css/dark.css` (generated), `templates/base.html`, `templates/includes/topbar.html`, `core/context_processors.py`, `core/icons.py`, `static/js/app.js`, `static/js/analytics.js`, `static/js/updates.js`, `build-css.ps1`, `build-css.sh` | Dark theme for the signed-in system (the public site stays light). Generated from the compiled stylesheet: the slate scale is redefined light-for-dark, white surfaces become the card colour, pale tints and dark text of every other colour are swapped, filled buttons keep their colour, dialog backdrops stay dark. Light / Dark / Device switch in the user menu, remembered per browser and applied before first paint; charts take matching grid, label and edge colours. A test fails if dark.css falls out of step with app.css |

`static/css/app.css` rebuilt with `tools/tailwindcss.exe` (it also picks up one class, `shrink`, left out of the previous build).

Also fixed: three multi-line `{# #}` comments added in this phase rendered as page text (Django comments are single-line); `core/tests_templates.py` now fails on any such comment.

Tests: `core/tests.py` (`RoleAwareDashboardTests`, `PhoneLayoutAndPlaceholderTests`, `AppearanceSwitchTests`), `core/tests_templates.py` (`TemplateCommentTests`, `DarkThemeTests`), `core/tests_live.py` (notification signal), `notifications/tests.py` (`BulkNotificationTests`), `incoming/tests.py` (`BulkAcknowledgeTests`), `core/tests_performance.py` (dashboard budget 12 with "My Work").

## 8. Improvement plan, Phase 5 - quality (2026-10-16)

| Task | File | Change |
|---|---|---|
| 5.1 | `services/tests.py`, `reports/tests.py`, `lgus/tests.py` | First tests for the three apps that had none (24): role rules for adding, publishing, approving and deleting; report workflow dates; upload checks; filters, summaries and CSV export |
| 5.1 (bug) | `core/views_base.py` | Deleting a record that others still depend on - an LGU with monitoring records - raised an unhandled `ProtectedError` (a server error). The shared delete view now says which records are in the way and returns to the record |
| 5.1 (bug) | `lgus/views.py` | The LGU export ran one query per row for "Latest monitoring"; it now reads the list's own annotation |
| 5.2 | `programs/models/` (was `models.py`, 1,835 lines), `programs/views/` (was `views.py`, 1,813 lines) | Split into packages by section - models: vocabulary, records, authority, documents; views: common, workbench, records, documents, authority. Done mechanically from a dependency analysis (no import cycles); every name re-exported from the package, so imports and the migrations' `programs.models.*_path` references are unchanged; no migration produced. Largest file now 779 lines |
| 5.3 | `.gitattributes` (new) | Git LFS tracks `docs/**/*.pdf`, `.docx`, `.pptx`, `.mp4`, `.png` from the next commit; the 99 files already in `docs/` are renormalised into LFS pointers. History is not rewritten, so the repository does not shrink, but it stops growing by the size of every new manual. Every clone needs `git lfs install` |
| 5.4 | - | Not done: Redis matters only on a server running several processes, and there is no server yet |
| 5.5 | `documents/models.py`, migration `documents.0009`, `documents/forms.py`, `documents/views.py`, `templates/dashboard/documents/detail.html`, `templates/dashboard/documents/list.html` | Document classification, Internal (default) or Confidential (decision of 2026-10-16). A confidential document is read only by its owner, focal person, whoever registered it, and Administrators: excluded from the register, the retention register, downloads, the viewer and the media gateway for everyone else; every workflow action and edit first requires being able to read it; it can never be published (`public()`, `is_available_publicly`, and the form refuses the combination) |
| 5.6a | `accounts/sessions.py` (new), `accounts/apps.py`, `accounts/views.py`, `accounts/urls.py`, `templates/accounts/profile.html` | "Where you are signed in" on My Profile: every live session of the account, with browser, address and time (noted in the session at sign-in - no new table), and "Sign out other devices", audit-logged |
| 5.6b | `notifications/management/commands/send_weekly_summary.py` (new), `templates/emails/weekly_summary.*`, `deploy/systemd/lgmed-weekly-summary.*`, `deploy/windows/register-weekly-summary.ps1` | Weekly summary email to everyone who reviews incoming documents: the "requires attention" counts, the ten most overdue incoming documents, who still owes the open month's MMIA/DTR. Run daily; sent once per ISO week per person (marked by a deduplicated notification, which also puts it on the bell); a failed send is retried on the next run; `--force` resends |

Tests: `documents/tests.py` (`ConfidentialDocumentTests`), `accounts/test_password.py` (`SignedInSessionTests`), `notifications/tests.py` (`WeeklySummaryTests`).
