# Monthly Submissions (MMIA and DTR)

Each month, LGMED staff upload two documents and nothing else:

1. **MMIA**: Monthly Monitoring Individual Accomplishments
2. **DTR**: Daily Time Record

The Division Chief sets the deadline for each reporting month. The system never picks a deadline itself. Before the deadline, staff can upload and replace their files. After it, uploads close until the Chief extends the deadline. Email and in-system reminders follow the Chief's deadline automatically.

Sidebar: **Information → Monthly Submissions** (`/app/monthly-submissions/`). Staff see their own page. The Division Chief sees the monitoring dashboard.

## Who does what

| Capability (accounts/models.py) | Held by | Allows |
|---|---|---|
| `must_submit_monthly` | Roles listed in `MONTHLY_SUBMISSION_SUBMITTER_ROLES` (default: LGMED Staff, Encoder) | Upload and replace your own MMIA and DTR, view your own history |
| `can_manage_monthly_submissions` | Administrator role (the Division Chief and designated administrators), System Administrator | Set, change and extend deadlines; monitor everyone; open any submitted file; send reminders; export the compliance report |

Viewers have neither capability, so they don't see the module. The System Administrator can also close the module to a role or an account in **Menu Permissions**. Every view checks its capability again on the server, whatever the sidebar shows.

**Scope:** LGMED-iMMS serves one division. A Division Chief therefore sees every account that is required to submit. If the system ever serves several divisions, narrow `services.submitters()` by `User.section`.

## Status

A status is never stored. It's calculated from the deadline, the current time and the uploaded files (`submissions/status.py`):

| Status | When | Colour |
|---|---|---|
| Not Submitted | Before the deadline, neither document is uploaded | Gray |
| Incomplete Submission | Before the deadline, one of the two is uploaded | Amber |
| Submission Completed | Both are uploaded (the time they were completed is shown) | Green |
| Overdue Submission | The deadline has passed and at least one is missing | Red |

Each staff member has exactly one status per month, so the dashboard totals always add up to Total Staff.

## Notifications

| Event | In-system (bell) | Email |
|---|---|---|
| Chief sets a deadline | Every staff member | "Monthly MMIA and DTR Submission Reminder" to every staff member |
| Chief changes or extends a deadline | Staff not yet complete | "Monthly Submission Deadline Extended/Updated" |
| 7, 3 and 1 days before, and on the day | Staff not yet complete | "Reminder: MMIA and DTR Due in N Days" / "Due Today", naming the missing document |
| One document uploaded | That staff member ("Your MMIA has been submitted. Your DTR is still pending.") | None |
| Both documents uploaded | That staff member, and the Division Chief | "Monthly Submission Successfully Completed" (staff only; the Chief gets no email) |
| Deadline passes with a document missing | Staff not yet complete | "Overdue Monthly MMIA and DTR Submission" |
| Chief clicks Send Reminder | The selected staff | "Reminder: Pending Monthly MMIA and DTR Submission", with the Chief's optional message |

Once someone has submitted both documents, they get no more pending reminders. Any "still pending" bell notices they had are cleared.

### How email delivery works

1. Each email is first written to `MonthlySubmissionNotification` under a **unique key**. If two reminder jobs overlap, the database accepts the key once and the other job skips it.
2. A row is **claimed** with an atomic conditional update before it's sent, so only one worker can send it.
3. A failed send is marked **FAILED** with the error, and the next run retries it every `MONTHLY_SUBMISSION_EMAIL_RETRY_MINUTES`, up to `MONTHLY_SUBMISSION_EMAIL_MAX_ATTEMPTS` times. An upload or a deadline change never fails because the mail server is down.
4. The email's content is put together **when it's sent**. If a reminder is still queued after the person has completed, or after the deadline has moved, it's marked SKIPPED and not sent.

Announcements, deadline changes, confirmations and manual reminders are sent straight away in a background thread (`MONTHLY_SUBMISSION_SEND_IMMEDIATELY`). Anything that thread doesn't finish is sent by the scheduled job.

The Chief's **View** page for a staff member lists every email sent to them for that month and whether it was delivered.

## The scheduled job (required for reminders)

The 7/3/1/0-day reminders and overdue notices don't depend on any event, so a scheduled job sends them:

```
venv\Scripts\python.exe manage.py send_submission_reminders
```

Run it **hourly**. It's safe to run any number of times. Reminders aren't sent before `MONTHLY_SUBMISSION_REMINDER_HOUR` (08:00 Asia/Manila). If the job misses a day, the next run sends the reminder that is due (for example, the 7-day reminder five days out). A reminder whose period began before the Chief set the deadline is skipped, because the announcement already covered it.

* **Windows (this development machine, or a Windows server):**
  `.\deploy\windows\register-submission-reminders.ps1` registers an hourly Task Scheduler task. It runs whether or not anyone is signed in, and doesn't need the web server or a browser. Output is written to `logs\submission-reminders.log`.
* **Linux production:** copy `deploy/systemd/lgmed-submission-reminders.service` and `.timer` to `/etc/systemd/system/`, then run `systemctl enable --now lgmed-submission-reminders.timer`.
* **Testing a schedule:** `manage.py send_submission_reminders --at 2026-10-25T09:00+08:00` shows what would happen at that moment. `--no-send` queues without sending.

**Without the scheduled job,** announcements, confirmations and manual reminders still go out, but the countdown reminders and overdue notices don't.

## Files and security

* Accepted formats: PDF, DOC, DOCX, XLS, XLSX, up to `MONTHLY_SUBMISSION_MAX_UPLOAD_MB` (10 MB).
* Each file is checked by its **content**, not its name (`submissions/validators.py`):
  * The file's first bytes must match its format.
  * A DOCX or XLSX must be a real package of that kind with no macros.
  * A PDF must not contain JavaScript, launch actions, embedded files or XFA.
  * Empty and oversized files are refused.
* Files are stored in `PROTECTED_MEDIA_ROOT/monthly_submissions/<year>/<month>/<user id>/`. Each stored name is made up of the document type and a random token; the uploaded filename is never used on disk. The uploaded filename is cleaned and kept only for display and as the download name.
* Protected storage has no URL. Files are sent only through `submissions:file` / `submissions:file_view`, which let the file's owner or a Chief through and refuse everyone else (403). Every view and download is recorded.
* A replaced file is deleted once the new one has been saved. Earlier months are never deleted.
* The module keeps its own trail (`MonthlySubmissionAuditLog`): uploads, replacements, completions, refused uploads, views, downloads, deadline changes and extensions, reminders, and exports. Uploads, deadline changes and exports are also recorded in the system-wide Audit Logs.
* This is not a virus scanner. On the server, on-access antivirus should cover the `protected` folder (see docs/security/).

## Settings (`<venv>/lgmed.env` or the environment)

| Variable | Default | Purpose |
|---|---|---|
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | (existing) | SMTP server. Without `EMAIL_HOST`, emails are printed to the console instead. |
| `LGMED_SITE_URL` | empty | The address used in email links sent by the scheduled job, e.g. `https://lgmed-imms.caraga.dilg.gov.ph` |
| `MONTHLY_SUBMISSION_MAX_UPLOAD_MB` | 10 | Upload size limit |
| `MONTHLY_SUBMISSION_REMINDER_DAYS` | 7,3,1,0 | Days before the deadline on which reminders are sent |
| `MONTHLY_SUBMISSION_REMINDER_HOUR` | 8 | Reminders wait until this hour (Asia/Manila) |
| `MONTHLY_SUBMISSION_SUBMITTER_ROLES` | LGMED_STAFF,ENCODER | Roles required to submit |
| `MONTHLY_SUBMISSION_EMAIL_MAX_ATTEMPTS` | 5 | Tries per email |
| `MONTHLY_SUBMISSION_EMAIL_RETRY_MINUTES` | 10 | Wait between tries |
| `MONTHLY_SUBMISSION_OVERDUE_WINDOW_DAYS` | 14 | Overdue notices only for deadlines that passed within this many days |
| `MONTHLY_SUBMISSION_SEND_IMMEDIATELY` | 1 | Send event emails at once in a background thread |

The nginx template allows 100 MB request bodies (`client_max_body_size`), which is well above this limit.
