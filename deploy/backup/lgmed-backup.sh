#!/usr/bin/env bash
# LGMED-IMMS nightly backup (TEMPLATE) - see docs/security/BACKUP_AND_RECOVERY.md
#
# Produces, under $BACKUP_ROOT/<timestamp>/:
#   database.sql.gz      consistent MySQL dump (single transaction)
#   media.tar.gz         public + internal uploads (MEDIA_ROOT)
#   protected.tar.gz     protected uploads (PROTECTED_MEDIA_ROOT)
#   SHA256SUMS           checksums, verified before any restore
# and encrypts each archive with the backup public key (age), so a copied
# backup disk does not hand over personal data.
#
# NOT included, on purpose: /etc/lgmed-imms/lgmed.env (SECRET_KEY,
# ESIRA_CREDENTIAL_KEY, passwords). Back those up separately, offline, under
# the administrator's custody - a backup that contains both the encrypted
# certificates and their key protects nothing.
#
# Install: copy to /usr/local/sbin/, chmod 750, run from root's crontab, e.g.
#   30 1 * * *  /usr/local/sbin/lgmed-backup.sh >> /var/log/lgmed-backup.log 2>&1
# Database credentials come from /root/.my.cnf ([mysqldump] user/password) for
# a backup account with SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT only.

set -euo pipefail
umask 077

APP_DIR="${APP_DIR:-/srv/lgmed-imms/app}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/lgmed-imms}"
DB_NAME="${DB_NAME:-lgmedimms}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
AGE_RECIPIENT_FILE="${AGE_RECIPIENT_FILE:-/etc/lgmed-imms/backup-recipient.txt}"

stamp="$(date +%Y%m%d-%H%M%S)"
target="$BACKUP_ROOT/$stamp"
mkdir -p "$target"

mysqldump --single-transaction --quick --routines --triggers \
    --default-character-set=utf8mb4 "$DB_NAME" | gzip -9 > "$target/database.sql.gz"
tar -C "$APP_DIR" -czf "$target/media.tar.gz" media
tar -C "$APP_DIR" -czf "$target/protected.tar.gz" protected

( cd "$target" && sha256sum ./*.gz > SHA256SUMS )

if command -v age >/dev/null && [ -s "$AGE_RECIPIENT_FILE" ]; then
    for file in "$target"/*.gz; do
        age -R "$AGE_RECIPIENT_FILE" -o "$file.age" "$file" && shred -u "$file"
    done
else
    echo "WARNING: backup is NOT encrypted (install age and set $AGE_RECIPIENT_FILE)" >&2
fi

# Retention: remove backup sets older than RETENTION_DAYS.
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+$RETENTION_DAYS" -exec rm -rf {} +

echo "Backup written to $target"
