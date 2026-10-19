# Going live

**Purpose:** taking LGMED-IMMS from the demonstration on a development PC to
real use by the Division, in order, without carrying any demonstration data
or demonstration account across.

**Who:** the System Administrator (ICT), with the Division Chief and the
records officer for the decisions marked **Decide**.

The technical detail of each server step is in
[security/PRODUCTION_DEPLOYMENT.md](security/PRODUCTION_DEPLOYMENT.md); this
page is the order to do things in and what must be true before moving on.

---

## 1. Before there is a server

- [ ] **Decide** where the system is hosted (office server, DICT GovCloud, or
      a VPS), with the Data Protection Officer: it holds personal data under
      RA 10173.
- [ ] **Decide** the hostname (for example a `caraga.dilg.gov.ph` subdomain)
      and get a TLS certificate for it.
- [ ] **Decide** the reference lists, by editing `core/reference_data.py`:
  - [ ] **Document types and retention periods** - with the records officer,
        from the approved Records Disposition Schedule. The values in the file
        are placeholders. They decide when documents fall due for review and
        disposal.
  - [ ] Sections of the Division.
  - [ ] Programme categories.
  - [ ] The LGU roster in `lgus/management/commands/seed_lgus.py`
        (names, income classes).
- [ ] **Decide** whether uploads are virus-scanned on the server (ClamAV,
      decision D3) or by endpoint protection on staff computers.
- [ ] Run a trial on the office network with the demonstration data
      (`run-lan.ps1`), one or two people per role, and fix what they find.

## 2. Build the server

Follow PRODUCTION_DEPLOYMENT.md sections 1-4. Then, before anything else runs:

- [ ] `/etc/lgmed-imms/lgmed.env` holds **new** values made on the server -
      never copied from the development PC's `venv\lgmed.env`:
  - [ ] `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`
  - [ ] `MYSQL_*` for an empty database
  - [ ] `ESIRA_CREDENTIAL_KEY` and `LGMED_MFA_KEY` - and **both copied to
        offline storage now**, apart from database backups. Losing them means
        every stored certificate and every authenticator must be set up again.
  - [ ] `LGMED_SITE_URL`, `EMAIL_*` (SMTP must work before accounts are made:
        new accounts receive their temporary password by email)
  - [ ] `LGMED_ACCEL_REDIRECT=1` with the nginx `/_internal/` locations in place
  - [ ] `DJANGO_DEBUG` **not set**, `LGMED_MFA_OFF` **not set**
- [ ] `manage.py check --deploy` shows no `security.*` warnings and no
      `lgmed.E001`; every `lgmed.W*` warning is understood.

## 3. An empty database, with real reference data only

```bash
manage.py migrate
manage.py setup_reference_data --dry-run     # read what it will create
manage.py setup_reference_data
manage.py createsuperuser                    # the System Administrator, typing their own password
```

- [ ] **Never** run `bootstrap_demo` or `seed_records` here (they refuse with
      DEBUG off).
- [ ] No database dump from the development PC is restored: everything there
      is demonstration data.
- [ ] `setup_reference_data` prints no "Demonstration accounts exist" warning.

## 4. Services and scheduled jobs

PRODUCTION_DEPLOYMENT.md section 6:

- [ ] `lgmed-imms` (Daphne) behind nginx, over HTTPS.
- [ ] `lgmed-submission-reminders.timer` (MMIA/DTR reminders, hourly).
- [ ] `lgmed-weekly-summary.timer` (the Chief's weekly email).
- [ ] Database backups scheduled from day one (security/BACKUP_AND_RECOVERY.md),
      and **one restore tested** on another machine.

## 5. First sign-in and accounts

- [ ] The System Administrator signs in, enrols an authenticator app (asked
      at first sign-in), and keeps the recovery codes somewhere safe.
- [ ] System Settings: records per page, the public website switch, the
      contact details on Public Website.
- [ ] Menu Permissions: which roles see which modules.
- [ ] Accounts for the Division, with each person's correct role. Each
      receives an email with a temporary password and must choose their own at
      first sign-in.
- [ ] The e-SIRA PNPKI trust roots (`ESIRA_PNPKI_TRUST_ROOTS`) installed before
      anyone registers a signing certificate.

## 6. Tell the staff, then open it

Before the first sign-in, everyone should know:

- [ ] Their temporary password arrives by email and must be changed at once.
- [ ] **Administrators, LGMED Staff and anyone who signs with a PNPKI
      certificate must set up an authenticator app** (Google or Microsoft
      Authenticator) at first sign-in - have a phone ready.
- [ ] Where to find the user manual, and who to call for help.

Then:

- [ ] A smoke test with real accounts: sign in, change password, record an
      incoming document and assign it, upload a file, open it in the viewer,
      mark a document Confidential and check another user cannot open it,
      submit an MMIA/DTR, sign an e-SIRA document.
- [ ] `DJANGO_HSTS_SECONDS` raised from 3600 to 31536000 once HTTPS is known
      to work on every name the site answers to.

## 7. The development PC afterwards

- [ ] It keeps running the demonstration only. Nothing real is entered there.
- [ ] Demonstration tunnels (`run-ngrok.ps1`, `run-cloudflare.ps1`) use the
      separate `lgmedimms_demo` database.
