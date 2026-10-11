# LGMED-IMMS Production Deployment

Step-by-step installation on a server. The reference layout is **Linux (Ubuntu 24.04 LTS or similar) + nginx + Daphne + MySQL 8.4 or later** (Django 6.1 refuses older MySQL), which the templates in `deploy/` implement. Section 9 adapts it to a Windows server.

Nothing in this guide should be run against production without the approval of the system owner. Do the whole procedure on a **staging** server first.

## 0. Architecture

```
Internet / office LAN
        │ 443 (HTTPS only; 80 redirects)
     [nginx]  ── /static/  → files on disk
        │      ── everything else, incl. /media/ and /ws/ → Daphne
        │ 127.0.0.1:8001
     [Daphne]  config.asgi:application  (user: lgmed, sandboxed by systemd)
        │ 127.0.0.1:3306 (or TLS to a DB host)
     [MySQL]   database lgmedimms, account lgmedimms (least privilege)
```

Never expose `manage.py runserver`, `run-lan.ps1` or `run-cloudflare.ps1` as the production service.

## 1. Server preparation

```bash
# Python 3.14 is not in Ubuntu 24.04's own repositories: use a distribution
# that ships it, or the deadsnakes PPA (sudo add-apt-repository ppa:deadsnakes/ppa).
sudo apt update && sudo apt full-upgrade
sudo apt install -y python3.14 python3.14-venv python3.14-dev build-essential \
     pkg-config default-libmysqlclient-dev nginx git unattended-upgrades
# MySQL 8.4 LTS: Ubuntu's own mysql-server is 8.0, which Django 6.1 refuses.
# Install 8.4 from the MySQL APT repository (https://dev.mysql.com/downloads/repo/apt/).
sudo dpkg-reconfigure -plow unattended-upgrades      # automatic security updates

sudo adduser --system --group --home /srv/lgmed-imms --shell /usr/sbin/nologin lgmed
sudo mkdir -p /etc/lgmed-imms && sudo chown root:lgmed /etc/lgmed-imms && sudo chmod 750 /etc/lgmed-imms
```

Firewall - only SSH (from the admin network) and HTTPS/HTTP:

```bash
sudo ufw default deny incoming
sudo ufw allow from <admin-network>/24 to any port 22 proto tcp
sudo ufw allow 80,443/tcp
sudo ufw enable
```

SSH: key authentication only (`PasswordAuthentication no`, `PermitRootLogin no` in `/etc/ssh/sshd_config`).

## 2. Database

```sql
-- as MySQL root
CREATE DATABASE lgmedimms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'lgmedimms'@'127.0.0.1' IDENTIFIED BY '<long random password>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
      ON lgmedimms.* TO 'lgmedimms'@'127.0.0.1';
-- Backup account (read-only)
CREATE USER 'lgmedbackup'@'localhost' IDENTIFIED BY '<another long random password>';
GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT ON lgmedimms.* TO 'lgmedbackup'@'localhost';
```

* MySQL listens on `127.0.0.1` only (`bind-address = 127.0.0.1`). If the database is on another host, open 3306 only to the application server's address and require TLS (`MYSQL_SSL_CA`).
* `CREATE/ALTER/INDEX/DROP/REFERENCES` are needed only while migrations run. For tighter least privilege, keep a separate migration account and revoke them from `lgmedimms` between releases.
* Generate passwords with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.

## 3. Application

```bash
sudo -u lgmed -H bash
cd /srv/lgmed-imms
git clone <repository-url> app && cd app
git checkout <release tag or commit>
python3.14 -m venv /srv/lgmed-imms/venv
/srv/lgmed-imms/venv/bin/pip install -r requirements.txt
mkdir -p media protected && chmod 750 media protected
```

## 4. Secrets and environment

Copy `.env.example` to `/etc/lgmed-imms/lgmed.env`, fill it in, then:

```bash
sudo chown root:lgmed /etc/lgmed-imms/lgmed.env && sudo chmod 640 /etc/lgmed-imms/lgmed.env
```

| Variable | Required | How to set it |
|---|---|---|
| `DJANGO_SECRET_KEY` | **yes** | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` - unique per server, never reused from development |
| `DJANGO_ALLOWED_HOSTS` | **yes** | The real hostname(s) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | yes | `https://<hostname>` |
| `MYSQL_PASSWORD` (+ `MYSQL_*`) | **yes** | From step 2 |
| `DJANGO_BEHIND_TLS_PROXY=1`, `DJANGO_TRUST_X_FORWARDED_FOR=1` | yes behind nginx | Only because the nginx template overwrites/appends those headers |
| `ESIRA_CREDENTIAL_KEY` | strongly recommended | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` - set **before** anyone stores a certificate; back it up offline |
| `EMAIL_*` | before creating accounts | Otherwise temporary passwords go to the log (`lgmed.W005`) |
| `RECAPTCHA_*` | if reachable from the internet | Google reCAPTCHA v3 keys for the hostname |
| `ESIRA_PNPKI_TRUST_ROOTS` | for e-SIRA | Paths to the DICT PNPKI CA certificates |
| `DJANGO_HSTS_SECONDS` | - | `3600` at first; `31536000` after step 8 passes |

**Missing required values stop the server at startup** with an explicit message - this is intentional. Leave `DJANGO_DEBUG` unset.

## 5. Database migrations and static files

```bash
cd /srv/lgmed-imms/app
set -a; . /etc/lgmed-imms/lgmed.env; set +a            # as a user allowed to read it
/srv/lgmed-imms/venv/bin/python manage.py check --deploy
/srv/lgmed-imms/venv/bin/python manage.py migrate --plan   # review what will run
/srv/lgmed-imms/venv/bin/python manage.py migrate
/srv/lgmed-imms/venv/bin/python manage.py collectstatic --noinput
/srv/lgmed-imms/venv/bin/python manage.py createsuperuser  # first System Administrator (is_superuser counts as one)
```

* Take a backup (BACKUP_AND_RECOVERY.md §2) **before** every `migrate` on an existing database.
* `check --deploy` must show no Django `security.*` warnings. Review every `lgmed.W*` warning and accept or fix it knowingly.
* Never run `bootstrap_demo` or `seed_records` on production (they refuse when DEBUG is off).

## 6. Services

```bash
sudo cp deploy/systemd/lgmed-imms.service /etc/systemd/system/
sudo cp deploy/nginx/lgmed-imms-proxy.conf /etc/nginx/snippets/
sudo cp deploy/nginx/lgmed-imms.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/lgmed-imms.conf /etc/nginx/sites-enabled/
# edit hostnames, certificate paths, /srv paths in both files
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl daemon-reload && sudo systemctl enable --now lgmed-imms
```

TLS certificate: from the agency CA or Let's Encrypt (`certbot --nginx`). Private keys `chmod 600`, owned by root.

The system runs as **one** Daphne process, which is what the in-memory WebSocket layer and sign-in throttle assume. To run several, set `LGMED_CHANNEL_REDIS_URL` and `DJANGO_CACHE_LOCATION` (Redis) first.

## 7. File permissions

| Path | Owner | Mode |
|---|---|---|
| `/srv/lgmed-imms/app` (code) | `lgmed` (or root) | `750`, files `640` - the service needs read only |
| `media/`, `protected/` | `lgmed` | `750` (uploads are written `640` by the app) |
| `/etc/lgmed-imms/lgmed.env` | `root:lgmed` | `640` |
| `staticfiles/` | readable by nginx (`www-data`) | `755` |

nginx must **not** be able to read `media/` or `protected/` - all files go through Django.

## 8. Post-deployment verification

Run the checks in [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) §2. In short:

```bash
curl -sI http://<host>/ | head -3                       # 301 to https
curl -sI https://<host>/accounts/login/ | grep -iE 'strict-transport|content-security|x-frame|x-content-type|referrer'
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/media/incoming/2026/01/x.pdf   # 404
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/app/                            # 302 to login
```

Then sign in as each role in a browser and exercise the pages listed in the checklist with the developer console open: there must be no `Content-Security-Policy` violation messages. If there are, set `DJANGO_CSP_REPORT_ONLY=1`, restart, report the messages, and fix before enforcing again.

When everything passes for a few days, raise `DJANGO_HSTS_SECONDS` to `31536000`.

## 9. Windows Server variant

The application is cross-platform; only the service wrappers change.

* **Reverse proxy:** IIS with URL Rewrite + Application Request Routing (enable WebSocket Protocol), or nginx for Windows / Caddy. Requirements are identical to the nginx template: HTTPS only, `X-Forwarded-Proto` overwritten, `X-Forwarded-For` appended, `/static/` from disk, **no** direct mapping of `media` or `protected`, request body limit ~100 MB, WebSocket upgrade on `/ws/`.
* **Daphne as a service:** NSSM (`nssm install LGMED-IMMS C:\lgmed\venv\Scripts\daphne.exe --bind 127.0.0.1 --port 8001 config.asgi:application`), working directory = the checkout, run as a dedicated low-privilege local account, environment from `<venv>\lgmed.env` (read automatically by settings).
* **ACLs:** `icacls` so only the service account and Administrators can read `lgmed.env`; service account has Modify on `media` and `protected` only.
* **Firewall:** Windows Defender Firewall - allow 443 (and 80 for the redirect) inbound; 8001 and 3306 must not be reachable from the network.
* **Updates:** Windows Update on an automatic schedule; Defender real-time protection on (it also gives on-access scanning of `media` and `protected`).
* **Backups:** Task Scheduler running `mysqldump` and a ZIP/7-Zip (AES) of `media` and `protected` - see BACKUP_AND_RECOVERY.md.

## 10. Releasing an update

1. Read the diff; run the test suite on staging (`python manage.py test`).
2. Back up (database + files).
3. `git fetch && git checkout <new tag>`; `pip install -r requirements.txt`.
4. `manage.py check --deploy`, `migrate --plan`, `migrate`, `collectstatic --noinput`.
5. `sudo systemctl restart lgmed-imms`; run the §8 checks.
6. If anything fails: rollback (BACKUP_AND_RECOVERY.md §5).
