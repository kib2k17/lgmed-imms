# LGMED-IMMS Incident Response

A short, practical procedure for the people who run the system. It does not replace the Department's ICT incident policy or the National Privacy Commission's rules; where they say more, they win.

## 0. Contacts (fill in and keep current)

| Role | Name | Phone | Email |
|---|---|---|---|
| System owner (Division Chief) | | | |
| System Administrator | | | |
| Regional ICT Unit | | | |
| Data Protection Officer (DPO) | | | |
| Hosting / network provider | | | |

## 1. First hour - any suspected incident

1. **Do not switch the server off** or wipe anything: memory and logs are evidence. Do not "clean up" before evidence is kept.
2. Write down what was seen, when, by whom - and keep writing a timeline from now on.
3. Tell the System Administrator and the system owner. If personal data may be involved, tell the DPO now (see §5 - the clock starts at discovery).
4. Preserve evidence: copy `journalctl -u lgmed-imms`, nginx `access.log`/`error.log`, and export the audit log (Audit Logs → filter by date → Export CSV) to offline media.
5. Contain - choose the smallest step that stops the harm:
   * one account misused → deactivate it (Users & Roles), reset its password and two-step verification;
   * the public site defaced or leaking → System Settings → switch the public website off;
   * the server itself compromised → isolate it from the network (firewall / disconnect), keep it running for analysis.

## 2. Scenarios

### A. A password, session or account may be compromised
* Deactivate the account; reset password and MFA (an Administrator cannot do this for a System Administrator - another System Administrator must).
* Review the Audit Logs for that account (sign-ins, IP addresses, exports, downloads, changes) back to the earliest suspicious event.
* Changing the password ends that account's other sessions automatically. To end **all** sessions for everyone: `python manage.py shell -c "from django.contrib.sessions.models import Session; Session.objects.all().delete()"`.
* Reverse unauthorised changes using the audit log's before/after values.

### B. A secret was exposed (committed to Git, pasted in chat, laptop lost)
Rotate the exposed secret, then everything derived from it:

| Exposed | Do |
|---|---|
| `DJANGO_SECRET_KEY` | Generate a new one, restart. All sessions and password-reset links become invalid (users sign in again). **If `ESIRA_CREDENTIAL_KEY` was not set**, stored signing certificates were encrypted with a key derived from the old secret: they become unreadable after rotation, and must be considered exposed if the database was also exposed - signers should re-upload, and consider asking DICT to revoke the certificates. |
| `ESIRA_CREDENTIAL_KEY` | If the database may also be exposed: treat stored PNPKI certificates and passphrases as compromised - signers request revocation from DICT and enrol new ones. Set a new key; stored credentials must be re-uploaded. |
| `MYSQL_PASSWORD` | `ALTER USER ... IDENTIFIED BY` a new password, update `lgmed.env`, restart. Check MySQL's general/audit log for foreign connections. |
| `EMAIL_HOST_PASSWORD` | Change it at the mail provider (revoke the app password), update `lgmed.env`. Check the mailbox's sent items for misuse. |
| `RECAPTCHA_SECRET_KEY` | Regenerate the key pair in the Google reCAPTCHA console. |
| TLS private key | Re-issue the certificate with a new key; revoke the old certificate with the CA. |
| Database backup | Treat as a data breach (scenario D). Note: TOTP secrets are stored in plaintext (audit finding M-06), so reset two-step verification for every account. |

A secret committed to Git stays in history even after deletion: rotating it is the fix, rewriting history is optional clean-up.

### C. Malware or a suspicious uploaded file
* Do not open the file. Note the record it belongs to (the audit log shows who uploaded it and from where).
* Copy it to isolated storage for analysis; scan with up-to-date antivirus.
* Remove it through the module (or, if the module does not allow deletion, have the System Administrator remove the record), and warn anyone who downloaded it (download events are in the Documents and e-SIRA trails).

### D. Personal data breach (RA 10173)
* Establish what data, whose, how many people, and since when - the audit log (who viewed, exported, downloaded) and the nginx access log are the main sources.
* The **DPO** decides on notification. Under NPC Circular 16-03, a breach that is likely to cause serious harm must be notified to the National Privacy Commission and to affected individuals **within 72 hours** of knowledge.
* Keep every record of the response; the NPC may ask for it.

### E. Defacement or unauthorised publication on the public website
* Switch the public site off (System Settings) to stop the harm immediately.
* Use the audit log to find what was published, by whom; withdraw it; restore the previous content from the audit trail's before-values or from backup.

### F. The server is compromised (unknown processes, modified files, unknown SSH keys)
* Isolate from the network; preserve disk and memory images if the ICT Unit can.
* Do **not** restore onto the same server. Build a new one from a clean OS image (PRODUCTION_DEPLOYMENT.md), restore data from a backup taken **before** the compromise, rotate **every** secret (scenario B, all rows), and then reconnect.

## 3. Recovery

* Restore from backup where data was lost or altered (BACKUP_AND_RECOVERY.md §3).
* Confirm with SECURITY_CHECKLIST.md §2 before reopening to users.
* Increase monitoring for a few weeks (daily audit-log review of sign-in failures and denials).

## 4. After the incident

Within two weeks, write a short report: timeline, root cause, data affected, what was done, what will change (and who, by when). Add new checks to SECURITY_CHECKLIST.md and, where possible, a regression test to `core/tests_security.py`.

## 5. Useful places to look

| Question | Where |
|---|---|
| Who signed in / failed / was throttled, from where | Audit Logs (Signed in, Failed sign-in, Access denied) |
| Who changed a record and what changed | Audit Logs → the record → field-level diff |
| Who downloaded a document / signed a PDF | Document's own trail (Documents); e-SIRA audit trail |
| Requests to the server | nginx `access.log`, `journalctl -u lgmed-imms` |
| Configuration at the time | `/etc/lgmed-imms/lgmed.env` (do not copy into tickets or chat) |
