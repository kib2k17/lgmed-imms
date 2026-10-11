# LGMED-IMMS Security Checklist

Tick each item and record who checked it and when. An unticked item in §1 blocks go-live; an item in §2 that fails means rolling back or fixing before users are told the system is live.

## 1. Before deployment

### Code and dependencies
- [ ] The release is a tagged commit; its diff since the last release has been read.
- [ ] `python manage.py test` passes on staging (the known pre-existing failure I-06 excepted, until fixed).
- [ ] `python manage.py makemigrations --check --dry-run` reports no changes.
- [ ] `pip-audit -r requirements.txt` reports no known vulnerabilities (or each one is assessed and recorded).
- [ ] No `.env`, `lgmed.env`, database file, export, key or certificate is tracked: `git ls-files | grep -Ei '\.(env|sqlite3|sql|pem|key|p12|pfx)$|export'` prints nothing.

### Configuration (`/etc/lgmed-imms/lgmed.env`)
- [ ] `DJANGO_DEBUG` is unset or `0`.
- [ ] `DJANGO_SECRET_KEY` freshly generated for this server (not copied from development or staging).
- [ ] `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` name only the real hostname(s).
- [ ] `DJANGO_BEHIND_TLS_PROXY=1` and `DJANGO_TRUST_X_FORWARDED_FOR=1` **only** with the nginx template's header handling in place.
- [ ] `ESIRA_CREDENTIAL_KEY` set, and a copy stored offline under the system owner's custody.
- [ ] SMTP configured (`EMAIL_*`), test email received.
- [ ] reCAPTCHA keys set if the site is reachable from the internet.
- [ ] `LGMED_MFA_OFF`, `DJANGO_LAN_ACCESS`, `ESIRA_ALLOW_UNTRUSTED_CERTIFICATES` absent.
- [ ] File is `root:lgmed 640`.
- [ ] `python manage.py check --deploy` shows no `security.*` warnings; every `lgmed.W*` warning is fixed or accepted in writing.

### Server and network
- [ ] OS fully patched; automatic security updates on.
- [ ] Firewall: only 443/80 public, 22 from the admin network only; 8001 and 3306 not reachable from outside the host (`ss -tlnp` shows Daphne and MySQL on 127.0.0.1).
- [ ] SSH key-only, no root login.
- [ ] Daphne runs as `lgmed` under the systemd template's sandboxing; never `runserver`.
- [ ] nginx has no `alias` or `root` for `/media/` or `/protected/`; `client_max_body_size` set; `server_tokens off`.
- [ ] TLS certificate valid for every hostname; private key `600` root.
- [ ] Database account `lgmedimms` has rights on `lgmedimms.*` only; backup account read-only.
- [ ] Backups scheduled and encrypted; **one restore rehearsed** on a separate machine (BACKUP_AND_RECOVERY.md §4).
- [ ] Log rotation in place (journald limits or logrotate for nginx); disk-space alert configured.

### Accounts
- [ ] No demonstration account (`lgmed.superadmin`, `lgmed.admin`, `lgmed.staff`, `lgmed.encoder`, `lgmed.viewer`) exists in the production database.
- [ ] Every administrator account has enrolled two-step verification.
- [ ] Each person has their own account; no shared logins.

## 2. After deployment (verify on the live host)

| # | Check | Expected | Result |
|---|---|---|---|
| 1 | `curl -sI http://<host>/` | `301` to `https://` | |
| 2 | `curl -sI https://<host>/accounts/login/` | `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` present | |
| 3 | Session cookie after sign-in (browser dev tools) | name `__Host-sessionid`, `Secure`, `HttpOnly`, `SameSite=Lax` | |
| 4 | `https://<host>/app/` signed out | `302` to `/accounts/login/` | |
| 5 | An internal attachment URL (copy from an incoming record) in a private window | `404` | |
| 6 | The same URL signed in | file opens | |
| 7 | A published announcement photo, signed out | image loads | |
| 8 | Six wrong passwords for a test account | sixth attempt shows "Too many unsuccessful sign-in attempts" | |
| 9 | Administrator opens a System Administrator's Edit / Reset password | `403` | |
| 10 | Encoder opens New Report | no Approved/Published in Status; New Announcement has no "Published" box | |
| 11 | Trigger a 404 (`/no-such-page`) | branded page, no stack trace | |
| 12 | `https://<host>/django-admin/` signed out | redirect to the system sign-in | |
| 13 | Browser console on: login (with reCAPTCHA), dashboard, analytics, updates dashboard, public Accomplishments, PPA upload & photo arrange, e-SIRA upload / route / workspace (PDF renders) / detail (Reject and Complete buttons), Menu Permissions, any "Print" button, year selectors | no CSP violation messages; every control works | |
| 14 | Notification bell updates / system notice appears without reload | WebSocket connected (`/ws/live/`) | |
| 15 | `https://www.ssllabs.com/ssltest/` (if internet-facing) | grade A or better | |

After a week without issues: raise `DJANGO_HSTS_SECONDS` to `31536000`.

## 3. Recurring

| Interval | Task |
|---|---|
| Daily (automatic) | Backup job succeeded; disk space |
| Weekly | Review audit log for `Failed sign-in` bursts, throttled sign-ins and `Access denied` |
| Monthly | OS and package updates applied; `pip-audit` on `requirements.txt`; review active accounts and roles; deactivate leavers |
| Quarterly | Restore test from backup; review Menu Permissions; rotate SMTP / database passwords if staff with access have left |
| Yearly | Renew certificates (if not automatic); re-run this checklist end to end |
