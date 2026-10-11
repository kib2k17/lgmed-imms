# LGMED-IMMS Backup, Recovery and Rollback

## 1. What must be backed up

| Item | Where | Why | Backed up by |
|---|---|---|---|
| Database | MySQL `lgmedimms` | Every record, account, audit trail | `deploy/backup/lgmed-backup.sh` (nightly) |
| Uploaded files | `media/` | Correspondence, documents, reports, photos | same script |
| Protected files | `protected/` | PPA internal files, e-SIRA PDFs and stored certificates (encrypted), profile photos, Data Sync workbooks | same script |
| Environment file | `/etc/lgmed-imms/lgmed.env` | `SECRET_KEY`, `ESIRA_CREDENTIAL_KEY`, passwords | **separately, offline** (see below) |
| Configuration | nginx site, systemd unit, TLS key | Rebuilding the server | separately, with the environment file |

A database backup without `media/` and `protected/` restores records whose files are missing; always keep the three from the same run together.

**Keys are kept apart from data.** The database backup contains Fernet-encrypted signing certificates; `ESIRA_CREDENTIAL_KEY` opens them. A backup set holding both protects nothing. Store `lgmed.env` (and the backup decryption key) on encrypted offline media in the system owner's custody, updated whenever a value changes.

## 2. Taking a backup

Scheduled: install `deploy/backup/lgmed-backup.sh` as described in its header (root crontab, 01:30 daily). It:

1. dumps the database in a single transaction (`mysqldump --single-transaction`), using a read-only backup account;
2. archives `media/` and `protected/`;
3. writes SHA-256 checksums;
4. encrypts each archive with `age` to the backup public key (`/etc/lgmed-imms/backup-recipient.txt`) - the private key is **not** kept on the server;
5. deletes sets older than 30 days.

Copy each night's set off the server (another building or an agency storage service) - a backup on the same disk does not survive the disk, ransomware, or a compromised server. Keep at least: 7 daily, 4 weekly, 12 monthly.

Manual backup before a release or migration:

```bash
sudo /usr/local/sbin/lgmed-backup.sh
```

Development and test environments must not receive production backups. If a production copy is ever needed to reproduce a fault, restore it on an isolated machine, and destroy it afterwards; record who had it and for how long (RA 10173).

## 3. Restoring

Restoring overwrites the database. **Only with the system owner's approval**, and after taking a backup of the current state first.

```bash
sudo systemctl stop lgmed-imms
cd /tmp/restore && cp -r /var/backups/lgmed-imms/<stamp>/* .
# decrypt with the offline private key
for f in *.age; do age -d -i /path/to/backup-key.txt -o "${f%.age}" "$f"; done
sha256sum -c SHA256SUMS                       # must say OK for every file

mysql -e "DROP DATABASE lgmedimms; CREATE DATABASE lgmedimms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
gunzip -c database.sql.gz | mysql lgmedimms

cd /srv/lgmed-imms/app
sudo -u lgmed mv media media.before-restore && sudo -u lgmed mv protected protected.before-restore
sudo -u lgmed tar -xzf /tmp/restore/media.tar.gz
sudo -u lgmed tar -xzf /tmp/restore/protected.tar.gz

sudo systemctl start lgmed-imms
```

Then: sign in, open a recent incoming document's attachment, an e-SIRA document, and a stored certificate (proves `ESIRA_CREDENTIAL_KEY` matches). Delete `/tmp/restore` and, once satisfied, the `*.before-restore` folders.

## 4. Restore test (quarterly)

On a separate machine (never production): restore the latest set as above, run `python manage.py check` and `python manage.py migrate --plan` (should list nothing), sign in, and open files from three modules. Record date, set restored, time taken and result. An untested backup is not a backup.

## 5. Rolling back a release

1. `sudo systemctl stop lgmed-imms`
2. If the release ran migrations: restore the database taken just before it (§3). Do not attempt `migrate <app> <previous>` on production unless every migration in the release is known to be reversible and you have the backup anyway.
3. `git checkout <previous tag>`; `pip install -r requirements.txt`; `python manage.py collectstatic --noinput`.
4. `sudo systemctl start lgmed-imms`; run SECURITY_CHECKLIST.md §2 items 1-6.
5. Record what happened and why in the change log.

## 6. Retention and deletion

* Records follow the office's retention schedule; the Documents module's archive/disposal workflow records each disposal and its authority.
* Backups older than the retention above are deleted by the script. Media that held backups (disks, USB drives) are wiped or destroyed when retired.
* The audit trail can be pruned with `python manage.py prune_audit_log` according to the retention the office sets; take a backup first.
