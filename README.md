# LGMED-iMMS

**Local Government Monitoring and Evaluation Division — Information Management
and Monitoring System**
Department of the Interior and Local Government, Regional Office XIII — Caraga

---

## Status

**All eight phases are complete and runnable.**

| Phase | Scope | State |
|---|---|---|
| 1 | Base layout, header, sidebar, top navigation, dashboard, responsive layout, Tailwind configuration, design tokens, reusable components | **Done** |
| 2 | Programs, Monitoring, LGU Management, Frontline Services, Documents, Reports, Calendar | **Done** |
| 3 | Users, roles, permissions, audit logs, system settings | **Done** |
| 4 | Analytics, exports, notifications, advanced filtering | **Done** |
| 5 | Incoming Monitoring: receive, review, assign, acknowledge, act, monitor, report | **Done** |
| 6 | Calendar and activity monitoring: whose activity, who may read it, the Chief's view of the office | **Done** |
| 7 | Document Management: register, assign, process, archive, authorised disposal | **Done** |
| 8 | Updates and Accomplishments: the Division's weekly record, the Chief's review, the Monday convocation, public publication | **Done** |

Announcements is now a working module: news, advisories and commendations are
encoded like any other record and published to the public website, which leads
with them. The site itself is run from **Public Website**
(`/app/settings/public-site/`, administrators and LGMED staff): what is
published right now, counted from the records, and the standing copy - the
homepage heading, the mandate, the office's contact details, the privacy and
accessibility statements - which used to be typed into templates.

The dashboard no longer uses sample data. Every figure, chart and list is a
query against the records; where there is nothing to count the panel says so
rather than drawing an empty axis.

**Incoming Monitoring** (`/app/incoming/`) replaces the spreadsheet the Division
kept for incoming correspondence. An encoder records what arrived; the Division
Chief reviews it, notes what it requires and names the focal person; the focal
person acknowledges the assignment and reports progress until the document is
closed. Every step is stamped with who did it and when, on the record itself.

**Updates & Accomplishments** (`/app/updates/`) is the Division's official
record of its own work. Authorised staff - the Division Chief included -
contribute activities, communications, accomplishments, photographs, POPS Plan
progress, ways forward and what is coming to **one weekly division record**,
updated every Thursday. The Chief reviews it, selects what leads the **Monday
convocation** and clears what the public may see. The figures are LGMEDD's
throughout: the module records what the Division accomplished, never a ranking
of who accomplished it.

---

## Running the system

```powershell
# 1. Dependencies (the virtualenv already exists in this working copy)
venv\Scripts\pip install -r requirements.txt

# 2. Database
venv\Scripts\python manage.py migrate

# 3. Reference data: the 78 LGUs of Region XIII
venv\Scripts\python manage.py seed_lgus

# 4. Demonstration accounts, one per role
venv\Scripts\python manage.py bootstrap_demo

# 5. Optional: illustrative records so the modules have content to show
venv\Scripts\python manage.py seed_records

# 6. Raise notifications for work that is already waiting
venv\Scripts\python manage.py refresh_notifications

# 7. Run
venv\Scripts\python manage.py runserver
```

To let someone outside this network see the running server, see
*Sharing a demo over ngrok* below.

| URL | Purpose |
|---|---|
| `/` | Public website — homepage, led by the news feed |
| `/announcements/` | LGMED Latest News: the public news feed |
| `/statistics/` | Regional figures, published as they stand in the records |
| `/documents/` | Public document library: search, filter by type and by year |
| `/accounts/login/` | Staff sign-in |
| `/app/` | Dashboard |
| `/app/programs/` `/app/monitoring/` `/app/lgus/` `/app/services/` `/app/documents/` `/app/announcements/` `/app/reports/` `/app/calendar/` | The eight modules |
| `/app/documents/monitoring/` `/app/documents/retention/` | Document monitoring, and the retention and archive register |
| `/accounts/users/` `/accounts/roles/` | Accounts and the permission matrix |
| `/app/settings/public-site/` | Public Website: what is published, and the site's standing text |
| `/app/settings/` `/app/audit-logs/` | System settings and the audit trail |
| `/app/analytics/` | Regional performance analysis |
| `/app/notifications/` | Your notification queue (also the header bell) |
| `/app/design-system/` | Living reference of every interface component |
| `/django-admin/` | Django administration (system administrators only) |

Demonstration accounts (password `LgmedDemo!2026`, development only):
`lgmed.superadmin`, `lgmed.admin`, `lgmed.staff`, `lgmed.encoder`, `lgmed.viewer`.

Sign in as `lgmed.viewer` and then as `lgmed.encoder` to see the difference:
the viewer has no Add or Edit buttons, and typing `/app/monitoring/new/`
returns 403 rather than the form.

### Seeded data — what is real and what is not

- **`seed_lgus` is reference data.** The 5 provinces, 6 cities and 67
  municipalities of Region XIII. **Verify the roster against the office's own
  records before relying on it** — names and classifications change, and only
  DILG's records are authoritative.
- **`seed_records` is illustrative.** Programs, monitoring activities,
  documents, reports, calendar entries, news items and three reporting weeks -
  one published, one reviewed, one still open - invented so the modules can be
  demonstrated. Remove them before the system carries live data:
  ```powershell
  venv\Scripts\python manage.py seed_records --clear
  ```
  It refuses to run with `DEBUG=False`.

---

## Secrets, and the sign-in check

No key is written into `config/settings.py`. That file is committed, so a value
placed in it would stay in the repository history for good and appear in every
screen share of the file. Settings read from the environment instead, and
`config/env.py` tops the environment up from a file kept **inside the
virtualenv**:

```
venv/lgmed.env
```

`sys.prefix` points at the virtualenv whenever its interpreter is running, so
the file is found whether or not `Activate.ps1` was run first - which matters,
because `venv\Scripts\python manage.py runserver` never runs it. `venv/` is
excluded by `.gitignore`, so nothing in the file can reach the repository. A
real environment variable of the same name always wins over it, which is how a
production host sets these the ordinary way and ignores all of this.

**The file is not tracked, so it does not survive rebuilding the virtualenv.**
If `venv/` is ever deleted, write it again:

```
RECAPTCHA_SITE_KEY=...        # public half; it appears in the page's HTML
RECAPTCHA_SECRET_KEY=...      # never leaves the server
RECAPTCHA_MIN_SCORE=0.5       # refuse anything Google scores below this
RECAPTCHA_TIMEOUT=5           # seconds to wait for Google
RECAPTCHA_ENFORCE=1           # 0 = log the verdicts, refuse nobody
```

Keys come from <https://www.google.com/recaptcha/admin> and are tied to the
domains listed there - add `localhost` or the check cannot verify in
development. Django restarts do not reload the file; restart `runserver` after
editing it.

### What the check does

reCAPTCHA **v3** shows no puzzle. The sign-in page asks Google for a token in
the background, posts it with the credentials, and `accounts/recaptcha.py`
asks Google what it thinks: a score from 0.0 (almost certainly automated) to
1.0 (almost certainly a person). Below the threshold the attempt is refused
**before the password is checked at all** - `LoginForm.clean()` settles the
verdict before `AuthenticationForm.clean()` can call `authenticate()` - so the
form cannot be used as an oracle for guessing passwords. Every refusal is
written to the audit log as a failed sign-in, beside the wrong passwords,
because on their own they are the shape of a scripted attack.

Three decisions worth knowing, because each one is a trade:

- **An outage at Google is not evidence of a bot.** If the verification call
  cannot be made - network down, timeout, malformed reply - the attempt is
  allowed through and the failure is logged loudly. The alternative is a third
  party's bad afternoon locking the whole office out of its own records. The
  password check still stands behind it. The same applies to a mistyped secret
  key: Django logs an error and lets people work.
- **A missing token is a refusal.** That is what protects the form, and it
  means the sign-in page needs JavaScript and reachable `google.com`. The page
  says so in a `<noscript>` notice. If the office network filters Google,
  either allow `www.google.com` or set `RECAPTCHA_ENFORCE=0`.
- **`RECAPTCHA_ENFORCE=0` is monitor mode**, not "off": verdicts still reach
  the audit log, nobody is refused. It is the sane way to switch the check on
  for the first time - watch the log for a week, confirm no real staff are
  being scored low, then set it to 1. Clearing the keys is what turns the
  check off entirely.

Google's floating badge is left where their script puts it, bottom-right of
the sign-in page. It overlaps the footer bar slightly, which is the price of
the only visible sign the page gives that it is protected at all. Their terms
allow hiding it *only* if the Privacy Policy and Terms are linked in the page
instead - so if it is ever hidden, that notice has to go back in. One of the
two must always stand. The badge is on the sign-in page alone; the script is
loaded nowhere else in the system.

---

## Sharing a demo over ngrok

The development server answers on `localhost` only, which is awkward when a
colleague in another office — or on their phone — needs to see the system.
**ngrok** opens an outbound tunnel from this machine and publishes it on an
HTTPS URL, so nothing has to be deployed and no firewall rule has to be asked
for.

```powershell
# Once per machine
winget install ngrok.ngrok
ngrok update                           # see the version note below
ngrok config add-authtoken <token>     # from dashboard.ngrok.com

# Every demo
.\run-ngrok.ps1 -Serve                 # starts runserver, then the tunnel
.\run-ngrok.ps1                        # tunnel only, server already running
```

`run-ngrok.ps1` finds `ngrok.exe` even when `winget`'s PATH edit has not reached
the open terminal, refuses to start without an authtoken rather than failing
later with an opaque service error, and warns when nothing is listening on the
port — a tunnel to a dead server returns 502 on every request and looks like an
ngrok fault.

### The agent winget installs is too old

`winget` ships ngrok **3.3.1**, and ngrok's service refuses any agent below
the minimum it currently enforces — 3.20.0 at the time of writing. The refusal
arrives as:

```
ERROR: authentication failed: Your ngrok-agent version "3.3.1" is too old.
ERR_NGROK_121
```

**"authentication failed" reads like a bad authtoken**, which sends you back to
the dashboard to re-copy a token that was never wrong. It is the agent version.
`ngrok update` upgrades the binary in place and is all that is needed; expect to
run it again after any `winget upgrade` that reinstalls the stale package.
`run-ngrok.ps1` checks the version up front and says this, so the misleading
message is not met twice.

### The reserved domain

A free ngrok account includes **one reserved domain**, claimed at
[dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains). Put it in
`venv\lgmed.env`, without a scheme:

```
NGROK_DOMAIN=lgmed-caraga.ngrok-free.app
```

Worth the two minutes it takes: without it every start produces a different
hostname, so the link mailed to ten people stops working the moment the tunnel
is restarted. `-Domain` overrides it for a single run.

### Why two settings have to change

A tunnelled request arrives carrying the ngrok hostname, not `localhost`, and
Django rejects a `Host` it does not recognise — so the first attempt answers
`DisallowedHost` instead of the homepage. Signing in then fails a second check:
the form post arrives with an `https://…ngrok-free.app` `Origin`, which CSRF
protection does not trust by default. Both are set in `venv\lgmed.env`:

```
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,.ngrok-free.app,.ngrok.app
DJANGO_CSRF_TRUSTED_ORIGINS=https://*.ngrok-free.app,https://*.ngrok.app
```

The leading dot is Django's subdomain wildcard, so an ephemeral hostname works
as well as the reserved one. It widens `ALLOWED_HOSTS` no further than ngrok:
`evil.example.com` is still answered with 400. Note that setting
`DJANGO_ALLOWED_HOSTS` **replaces** the default list, which is why `localhost`
and `127.0.0.1` are repeated in it.

These two lines live in `venv\lgmed.env` and must stay there. That file is never
committed, and a production host must not trust an ngrok hostname — see
*Secrets, and the sign-in check* above for why this project keeps such values
out of `config/settings.py`.

`DJANGO_BEHIND_TLS_PROXY` is deliberately **not** set. ngrok terminates TLS and
forwards plain HTTP, so Django sees an insecure request — harmless here, because
`DEBUG=True` leaves `SECURE_SSL_REDIRECT` off, and the system builds no absolute
URLs that could turn into blocked mixed content. Setting it would mean trusting
a header a client can forge.

### What a visitor sees

- The **public site** (`/`, `/announcements/`, `/statistics/`, `/documents/`) is
  open, exactly as it is on localhost.
- Everything under `/app/` still requires a sign-in, and role permissions apply
  unchanged — a viewer account remains read-only over the tunnel.
- ngrok's free tier shows a **browser warning page first**. Visitors click
  *Visit Site* once per browser; it is not a fault in the system.
- The **sign-in reCAPTCHA is registered per domain**, so a new hostname fails
  the check until it is added to the key's domain list at
  [google.com/recaptcha/admin](https://www.google.com/recaptcha/admin). The
  reserved domain has been added alongside `127.0.0.1` and `localhost`, so the
  real check runs over the tunnel — an ephemeral hostname will not, which is a
  second reason to reserve one. Two traps when adding it: the field wants a
  **bare host**, no scheme, path or port (`….ngrok-free.app`, not
  `https://…/accounts/login/`), and an entry only counts once **+** has turned
  it into a listed row and the page has been saved. Never register the bare
  `ngrok-free.app`: reCAPTCHA matches subdomains, so that would let any ngrok
  site on the internet use this key.
- Should it ever fail anyway, **sign-in still succeeds**: the page detects the
  failure, posts an empty token, and `RECAPTCHA_ENFORCE=0` lets it through
  while recording the miss in the audit log.
- `http://127.0.0.1:4040` is ngrok's inspector — every request, with headers and
  response, which is the fastest way to see what a remote browser actually sent.

### Before opening a tunnel

This publishes a `DEBUG=True` server, so an unhandled error returns a traceback
with source and local variables to whoever triggered it. The demonstration
accounts share a password printed in this README and in `acounts.txt`. Anyone
holding the URL can reach the sign-in page.

So: tunnel the **demonstration** database, not live LGU records; stop the tunnel
(Ctrl+C) when the demo ends rather than leaving it up overnight; and treat the
URL as semi-public — a reserved ngrok domain is guessable by design. Once the
system carries real data, it belongs behind the deployment in *Before
deployment* below, not behind a tunnel.

---

## Stylesheet build

Tailwind CSS is compiled ahead of time by the **standalone Tailwind CLI**. No
Node.js, no `npm install`, no CDN request at runtime — the stylesheet, the Inter
typeface and Chart.js are all served from `static/`, so the system works on an
isolated government network.

```powershell
.\build-css.ps1           # one-off, minified
.\build-css.ps1 -Watch    # rebuild while editing templates
```

`tools/tailwindcss.exe` is not committed (134 MB). On a new machine, download the
Windows build of Tailwind CSS v4.1.13 from the tailwindcss GitHub releases page
and save it as `tools/tailwindcss.exe`.

**Rebuild the stylesheet after adding new utility classes to a template** —
Tailwind only emits classes it finds in the files listed by the `@source`
directives in `static/css/app.src.css`.

---

## Architecture

```
Django backend  →  Django templates  →  Tailwind CSS  →  vanilla JavaScript  →  Chart.js
```

No React. No JavaScript build step. Everything a government developer needs to
change is a template, a CSS class, or a plain `.js` file.

```
config/                  Project settings and root URLconf
accounts/                Custom user model with the five LGMED-iMMS roles
core/                    The shared layer every module is built on
  views_base.py          Generic list / detail / form / delete views
  forms_base.py          GovModelForm: styling and sectioned fieldsets
  mixins.py              Capability-based authorization
  navigation.py          The sidebar, defined once, with per-item permissions
  stats.py               Dashboard figures, queried from the records
  status.py              Record status -> the four status colours, in one place
  icons.py               Inline SVG icon set (no icon font, no CDN)
  templatetags/ui.py     {% icon %}, {% status_badge %}, {% sort_link %}, ...

lgus/  programs/  monitoring/  services/  announcements/
reports/  activities/
                         One app per module: models, form, views, urls, admin
documents/               Document Management - the Division's document register
  models.py              The document, its versions, its trail, retention
  workflow.py            Every transition, and what each one sets off
  forms.py               A separate form per decision, so the trail can say which
incoming/                Incoming Monitoring - correspondence received
  models.py              The document, its updates, and its own trail
  workflow.py            Every transition, and what each one sets off
  reports.py             The ten monitoring reports, described once
  forms.py               A separate form per hand the document passes through
announcements/           News, advisories and commendations for the public site
updates/                 Updates and Accomplishments - the Division's own record
  models.py              The reporting week, and everything contributed to it
  stats.py               Division figures and charts - no per-employee dimension
  forms.py               A separate form per decision, including the Chief's

analytics/               Performance analysis
  metrics.py             Coverage, trend, turnaround - series plus figures
notifications/           Who gets told what, and when
  service.py             Audiences, deduplication, withdrawal
  signals.py             Event notifications from status transitions
audit/                   The append-only trail
  recording.py           How an action reaches the log; field-level diffs
  signals.py             What is audited, plus login/logout handlers
  middleware.py          Carries the request to the signal handlers
administration/          System settings, the reference lists, the public site
  models.py              SystemSetting and PublicSiteContent: cached singletons
  reference.py           Program categories, document types, provinces
  views.py               Settings, and the Public Website backend

templates/
  base.html              Authenticated application shell
  public_base.html       Public website shell
  public/                Homepage, news, statistics, document library, about
  includes/news_card.html         One item on the public news feed
  dashboard/module_list.html      Generic table page every module extends
  dashboard/module_form.html      Generic sectioned data-entry form
  dashboard/module_confirm_delete.html
  includes/              topbar, sidebar, footer, alerts, breadcrumbs, pagination
  components/            stat_card, mini_stat, chart_card, table_toolbar,
                         th_sort, row_actions, bound_field, modal, empty_state,
                         detail_actions, record_provenance
static/
  css/app.src.css        Design tokens and component classes (source)
  css/app.css            Compiled stylesheet (generated — do not edit)
  js/app.js              Drawer, menus, dialogs, Chart.js defaults
```

### How to add a module

The shared layer does the work; a module supplies a model, a form and roughly
forty lines of view code:

```python
class ThingListView(ThingModuleMixin, ModuleListView):
    search_fields = ("title", "lgu__name")     # what the search box searches
    filter_fields = (("status", "Status", Status.choices),)
    sort_fields   = ("title", "created_at")    # whitelist for sortable headers
    export_columns = (("Title", "title"), ("LGU", "lgu.name"))
```

That gets search, filtering, sortable headers, pagination, CSV export of the
*filtered* rows, the empty state and the permission rules — identical to every
other module.

### Design decisions worth knowing

- **Design tokens live in `@theme`** in `static/css/app.src.css`: the
  institutional blue scale, the typography scale (`text-page-title`,
  `text-section-title`, `text-card-title`, `text-meta`), sidebar width and the
  three shadow levels. Change a token there and the whole system follows.
- **Status is never colour alone.** `{% status_badge %}` renders a colour, a
  glyph and a text label. `core/status.py` maps every record value onto one of
  five tones, and a test fails if a model adds a status nobody mapped.
- **Charts carry their own data table.** Each panel has a “View figures”
  disclosure containing the same numbers as a real `<table>` — available to
  screen readers, to print, and when JavaScript fails.
- **Permissions are enforced in the view, not by hiding buttons.** The sidebar
  and the Add/Edit/Delete controls hide what a user cannot do as a courtesy;
  `core/mixins.py` raises `PermissionDenied` regardless, and the tests assert
  that a viewer POSTing to a create URL is refused.
- **Deletion always requires confirmation**, on a full page that works without
  JavaScript; the in-page dialog posts to the same URL.
- **Every record carries its provenance** — who encoded it, who last changed
  it, and when — shown on the record itself, not only in a log.
- **Sorting is whitelisted.** `?sort=` is checked against `sort_fields`, so an
  arbitrary column name never reaches the ORM.

### Phase 3: accountability

- **The audit trail is written by signals, not by views.** Every operational
  model is connected to `pre_save`/`post_save`/`post_delete`, so a record
  cannot be changed through a view, the Django admin, a management command or
  the shell without leaving an entry. `pre_save` reads the stored row to
  produce a real field-level diff (one extra query per update).
- **Entries denormalise the actor's name and the record's label.** A log that
  says "deleted by NULL" because the account was later removed is not a log. A
  test deletes a user and asserts the entry still names them.
- **Passwords never reach it**, and a failed sign-in records the username that
  was tried but not the password.
- **The log is append-only.** There is no create, edit or delete URL, the list
  page offers no create action, and the Django admin refuses all three - each
  asserted by a test. Entries are removed only by `prune_audit_log`, a
  server-side command that refuses a retention period under a year and records
  its own run so the gap in the log is explained.
- **Roles are defined in code, not edited at runtime**, because they gate
  server-side checks; making them editable would let access be widened without
  the change passing review. `/accounts/roles/` generates the matrix from the
  same properties the views enforce, so the page cannot drift from reality.
- **Accounts are deactivated, never deleted**, so their history stays
  attributable. An administrator cannot change their own role or deactivate
  their own account.
- **Every system setting is wired to something.** `records_per_page` drives
  pagination in every module, `notice_message` renders a banner, and
  `public_site_enabled` takes the public pages to a 503 maintenance notice
  while leaving staff sign-in working. Each has a test that changes the setting
  and then checks the effect.

### Branding

The official DILG seal lives at `static/img/dilg-logo.png` and is rendered by a
single partial, `templates/includes/agency_logo.html`:

```django
{% include "includes/agency_logo.html" with size="size-9" %}
{% include "includes/agency_logo.html" with size="size-11" on_dark=True %}
```

- The seal is transparent with black lettering, so `on_dark` sets it on a white
  disc rather than dropping it onto navy where its text would vanish.
- It is decorative in every current placement, because each one sits beside
  text that already names the department; `alt_text` is there for a placement
  where the mark stands alone.
- If the asset is missing the partial falls back to a plain `DILG` wordmark. It
  never draws an approximation of the seal - a government seal is either the
  real one or it is a placeholder.

### Phase 4: analysis and attention

- **Notifications are addressed to a person, never to a role.** An unread count
  therefore means "things *you* have not dealt with", which is the only reading
  that makes a count worth showing.
- **Two kinds, because they answer different questions.** A report moving to
  "for review" is an *event*, raised from a signal so it fires whether the
  change came from the interface, the admin or the shell. A follow-up falling
  overdue is not an event - nothing happens on that day - so standing
  conditions are found by `refresh_notifications`, run on a schedule.
- **A notice withdraws itself when the work is done.** Approving a report stops
  it asking to be reviewed. Withdrawn notices are dismissed rather than
  deleted, so the record of what people were told survives.
- **A standing problem is notified once.** `dedupe_key` identifies the
  underlying condition, so a follow-up three weeks overdue produces one
  notification, not twenty-one.
- **Analytics answers the performance-review questions**, not the daily ones:
  coverage by province, this year against last, and average days from a
  report's submission to its publication. The most useful panel is the least
  glamorous - **Least-Monitored LGUs** names the LGUs the Division has not
  reached, in the order it should reach them.
- **Every export is recorded in the audit trail**, with the row count and
  whether filters were active. Taking data out of a government system is an
  action worth logging.
- **Date ranges and multi-value filters** are part of the shared layer: a module
  gets a from/to range by declaring `date_field`, and a repeated query
  parameter (`?status=A&status=B`) selects rather than narrowing to whichever
  value the browser sent last. The range is carried into the CSV export, so an
  exported file matches the screen it came from.

### Phase 5: Incoming Monitoring

The module exists to enforce one rule the spreadsheet could not:

```
RECEIVE → RECORD → REVIEW → TAKE NOTE → ASSIGN → ACKNOWLEDGE
        → ACTION → UPDATE → MONITOR → COMPLETE → REPORT
```

- **The encoder records; the Chief decides.** A recorded document starts at
  *For Division Chief review* with no focal person, and there is no path by
  which an encoder can name one. That rule is enforced three deep: the
  encoder's form has no `assigned_to` field at all, so no version of the
  request can carry one; the assign URL is a POST of its own, refused to anyone
  without `can_review_incoming`; and `workflow.assign` raises `PermissionDenied`
  itself, so the shell and a management command are refused on the same terms
  as a button.
- **`can_review_incoming` is a capability, not a new role.** It is held by the
  ADMIN role - the Division Chief and designated administrators - and is
  deliberately narrower than `can_approve`. It appears in the permission matrix
  at `/app/settings/roles/` alongside the others, generated from the same
  property the views enforce.
- **Every transition goes through `incoming/workflow.py`.** One function per
  step, each writing the trail entry, the status change and the notification
  together. A second view added later cannot remember two of the three.
- **The document carries its own trail**, shown on the record: received,
  reviewed, assigned, acknowledged, acted on, returned, completed - each with
  the actor's name and role copied in, as in the audit log, so an entry
  survives the account being removed. The system-wide audit log records the
  same changes at the row level.
- **An update *is* the status change.** The focal person reports what they did
  and the status that leaves the document in, in one act. Asking for the two
  separately is how a record ends up reading "In progress" three weeks after
  the work was finished.
- **Overdue is derived, never stored.** `due_date` plus "not completed" is the
  whole definition, stated once on the queryset and reused by the list filter,
  the dashboard figure, the report and the notification digest.
- **Awaiting an update** means assigned, unfinished, and nothing heard for
  `UPDATE_REMINDER_DAYS` (7) - measured from the last update where there is
  one and from the assignment where there is not, so a document assigned this
  morning is not already counted as silent.
- **Every figure on the Chief's dashboard is a link** to the documents it
  counted. A figure you cannot click through to is a figure you have to take on
  trust.
- **Ten monitoring reports**, described once in `incoming/reports.py` and driven
  by one view, so the page and the CSV are the same figures under the same
  filters - which is what makes the exported file safe to attach to a
  memorandum. The export is logged in the audit trail like every other.

### Phase 6: the work calendar

`/app/calendar/` is no longer a shared noticeboard of division events. It is a
**work-planning and monitoring system**: employees record what they are doing,
and the Division Chief sees who is doing what, when, and where, without anyone
losing ownership of their own plan.

- **Every activity belongs to somebody.** `owner` is the employee whose
  activity it is; `assigned_to` is the employee expected to carry it out when
  that is somebody else. The two are kept apart deliberately - "Rosario planned
  this" and "Antonio is doing it" are different facts, and a single field
  collapses them into a guess.
- **Visibility is the owner's decision, and it defaults to Private.** The four
  levels are Private, Assigned users, Team (the owner's section) and
  Organization-wide. A personal plan is nobody else's business unless its owner
  says otherwise.
- **Supervisors read; they do not rewrite.** `can_supervise` (the ADMIN role -
  the Division Chief) grants sight of every activity in the office, whoever
  owns it and whatever its visibility. Changing another employee's activity is
  a separate, narrower capability, `can_manage_any_activity`, held by the
  system administrator alone. A calendar the Chief can silently edit is not a
  record of what an employee planned.
- **The enforcement is one queryset.** `CalendarActivity.objects.visible_to(user)`
  is the starting point of the list, the record page, the edit form, the delete
  confirmation, the CSV export and the dashboard's "upcoming" panel. An activity
  a user may not see returns **404** whatever primary key is typed at it; one
  they may read but not change returns **403**. Neither answer depends on a
  template hiding a button.
- **The assignee may report progress, and only that.** `/<pk>/progress/` is a
  POST of its own taking a status and remarks. The employee doing the work
  should not have to ask the owner to record that it is done - but they cannot
  move the date, the venue or the visibility while they are there.
- **The day box is the control, not the numeral.** Clicking anywhere in a day
  opens a dialog listing everything on it - all of it, not the three the cell
  had room for. The dialog is built from markup the page already carries, so it
  opens instantly and adds no second endpoint that would have to repeat the
  permission checks. A `<td>` cannot be a link and the activity chips inside it
  are links already, so the cell uses an overlay anchor with the chips lifted
  above it: a click on an activity opens that activity, a click anywhere else
  opens the day. Without scripting the overlay is an ordinary link and the day
  is listed beside the grid instead.
- **Clicking a day opens a form, not just a view.** Adding is what people come
  to a calendar to do, so the day dialog leads with a short form - eight fields,
  the date already filled in from the box that was clicked - and lists what is
  already on that day above it, so the clash is visible before it is created.
  `QuickActivityForm` subclasses the full form rather than restating it, and
  posts to the ordinary create URL with `quick=1`: one view, one set of
  ownership rules, one save. A quick way in must not become a second way in. An
  invalid post renders the full page with its errors, which is also what a
  browser without scripting gets.
- **`next` is checked before it is followed.** The dialog sends the calendar's
  own address so a save returns to the month, scope and period it was made
  from. It arrives in a form post, and an unchecked redirect target is an open
  redirect however innocuous the form around it looks.
- **The filter bar runs the full width, above both columns.** It began inside
  the list card, which is a third of the page wide: six controls that each want
  a row ended up stacked one per line and pushed the activities they filter off
  the bottom of the screen. `table_toolbar.html` takes a `standalone` flag that
  drops its bottom rule, since the rule exists to separate it from a table that
  is not there.
- **A card is its own height, and the grid spends what is left.** Grid items
  stretch by default, so the month grid - always shorter than a list of
  everything in the month - was inflated to match the list beside it and
  carried a slab of empty card below its legend. The row is `items-start` now,
  and the calendar opts back into the stretch, because it is the one of the two
  that can use the height: the table fills the card and the day rows share it
  out, which is also more room for the wrapped titles. A list cannot fill
  space, so it is left at its natural height. The stretch is capped at 64rem -
  a busy month for the Chief lists forty activities beside a six-row grid, and
  matching that would give each day a cell the size of a postcard.
- **Each dialog scrolls in exactly one place.** The height cap and the flex
  column live on a wrapper inside the `<dialog>`, with the heading and the
  buttons pinned either side of a single scroll container - so Save is always
  reachable, and there are never two scrollbars side by side with the outer one
  doing nothing. The cap cannot go on the `<dialog>` itself: an author
  `display:flex` beats the browser's own `dialog:not([open]) { display: none }`,
  because author styles outrank the user-agent sheet whatever the specificity,
  and the dialog would then sit on the page permanently. The Save button lives
  in the pinned footer, outside the form, and reaches it through the `form`
  attribute - the same trick `components/modal.html` uses.
- **Day-cell titles wrap; they do not truncate.** "1:30PM SGL..." tells a
  reader nothing they came to the calendar for. The title wraps to at most
  three lines and the row grows to fit, which is what a calendar with real
  entries in it should do. Three lines is a ceiling rather than a target -
  titles run to 255 characters in the model, and one pathological entry should
  not push a week off the screen - and the whole title is always sent to the
  page, so the tooltip, the day dialog and the record are never short.
- **The grid abbreviates the time; it does not change it.** A day cell shows
  "1PM" rather than the localised "1p.m.", which spends five of the roughly
  eighteen characters a cell holds on punctuation - but minutes appear whenever
  there are any. The hour alone rendered a 9:45 briefing as "9AM", which is a
  different time rather than a shorter way of writing the same one.
- **Two navigations, because there are two questions.** *Scope* asks whose
  activities (my calendar, assigned to me, shared with me, all employees);
  *period* asks over what stretch (month, week, upcoming, overdue). They compose,
  and both survive a filter being applied.
- **The Chief's monitoring page** (`/app/calendar/monitor/`) is a workload, not
  a calendar: open, upcoming, overdue and completed counts per employee and per
  section, what is running today, what is planned, what has slipped. Every
  figure links through to the activities behind it.
- **Departments, divisions and sections are a reference list**, maintained at
  `/app/settings/#sections` like program categories and document types. An
  employee belongs to one; an activity takes its owner's unless told otherwise.
  This is what makes "by division" a grouping rather than a string match.
- **Publishing to the public site requires office-wide visibility.** The form
  refuses the contradiction, and `core.views.public_calendar` checks the
  visibility level as well as the published flag - the Django admin does not
  run form validation, and the public site should not depend on it.

### Phase 7: Document Management

`/app/documents/` was a repository — a title, a type, a year and a file. It is
now the Division's **document register**: every document received, created,
submitted or processed, whatever its type, recorded and traceable from arrival
to authorised disposal.

```
RECEIVED/CREATED → REGISTERED → REVIEWED → ASSIGNED → PROCESSING
                 → APPROVAL → COMPLETED → RETENTION → ARCHIVED
                 → RETENTION REVIEW → AUTHORISED DISPOSAL or PERMANENT PRESERVATION
```

Three faces, one sidebar entry, because they are one job: the **register**
(`/app/documents/`), the **monitoring dashboard** (`/app/documents/monitoring/`)
and the **retention and archive register** (`/app/documents/retention/`).

- **Every document has an owner.** `owner` is the person answerable for it, and
  the field is not nullable — nothing is filed anonymously. `assigned_to` is the
  focal person processing it when that is somebody else. The two are different
  facts and a single field would lose one of them.
- **The encoder records; the Chief assigns.** The same rule as Incoming
  Monitoring, enforced the same three ways: the registration form carries no
  `assigned_to` and no `status` field at all; the assign URL is a POST of its
  own; and `workflow.assign` raises `PermissionDenied` for anyone without
  `can_assign_documents`. A hidden button is a courtesy, never the control.
- **A file is never replaced.** Uploading a revision writes a new
  `DocumentVersion` and keeps the old one, with the reason it was superseded —
  which is required, not optional, because a stack of files with no explanation
  answers "did it change?" and not "why?". `Document.file` is then pointed at
  the *same stored file* as the newest version rather than given a copy of it:
  one file on disk, two rows referring to it, instead of doubling the storage
  every revision.
- **Control numbers come from a counter, not from a maximum.**
  `ControlNumberSequence` holds the last number issued for each year and only
  ever counts up. Deriving the next number from `MAX(reference_number)` looks
  equivalent until the newest document is deleted, at which point the register
  reissues a number it has already used. Gaps are tolerable; duplicates are not.
- **Files are never served from `MEDIA_URL`.** Every download goes through
  `DocumentDownloadView`, which re-checks access and writes the download to the
  document's trail. A register that logs who downloaded what while also handing
  out permanent URLs that bypass the log is only pretending to. A file the
  database knows about but storage does not reads as 404, not as a server fault,
  and no download is recorded for a file that never opened.
- **Views are recorded once a day per person; downloads always.** A row for
  every page open would bury the trail in noise and make it useless for the acts
  that actually changed something. One entry per person per day still answers
  "who has seen this?".
- **Archiving removes nothing.** The metadata, the ownership, every version and
  the whole trail stay exactly as they were; what changes is who may reach it.
  Archived documents are also dropped from the working register unless the
  archive is what was asked for, and taken off the public website — archived and
  still published is a contradiction the public would be the last to notice.
- **Retention is a property of the document type**, because that is how a
  records schedule works: an office decides once that memoranda are kept for
  five years. Completing a document starts its clock from its type. A type
  carrying no period leaves `retention_until` unset and the document shows as
  having no policy — a visible gap the records officer can close, rather than an
  invisible one. "Nobody has decided yet" must never become "dispose of it
  today".
- **Disposal is the only irreversible act, and is the narrowest capability in
  the system.** It needs four things at once: `can_dispose_documents`, an
  archived document, a retention decision that actually says to dispose of it,
  and a `DisposalAuthority` — a board resolution or approved records disposal
  schedule, recorded first and then cited by each disposal made under it. The
  form also asks for the word DISPOSE to be typed. The files are destroyed; the
  record, its ownership, its version list and its complete trail are kept,
  because that is precisely what a disposal has to be able to prove afterwards.
- **Two trails, deliberately.** `audit.AuditEvent` records that a row changed;
  `DocumentEvent` records what happened to the document in the office's own
  words — registered, viewed, downloaded, assigned, revised, archived, disposed
  of — and is shown on the record itself. Accountability nobody can see is not
  accountability. As in the audit log, the actor's name and role are copied in,
  so a trail never reads "archived by NULL" because an account was later removed.
- **Every figure on the monitoring dashboard is a link** to the documents behind
  it, the same rule as Incoming Monitoring.

Three new capabilities appear in the permission matrix at `/app/roles/`:
`can_assign_documents` (the Chief and administrators), `can_archive_documents`
(the roles that already approve and publish) and `can_dispose_documents`
(administrators). Document types now carry their retention period, and disposal
authorities are a reference list, both maintained at `/app/settings/`.

**One migration note.** The old `PUBLISHED` status no longer exists. A published
document had been approved and released, which in the new lifecycle is
`COMPLETED`; `is_public` is what actually kept it on the public website and is
untouched, so nothing left the public library. Migration `0003` also gives every
existing document an owner, a control number and a version 1 pointed at the file
it already had.

### Phase 8: Updates and Accomplishments

`/app/updates/` is the Division's official record of its own work. It is a
**division accomplishment system, not an employee performance monitor**, and
that single decision shapes every model, every figure and every page in it:

> Staff contribute the information, but the accomplishment belongs to the
> Division.

```
Staff input → Division consolidation → Chief review → Monday convocation → Public publication
```

The record is a **week of LGMEDD**, not a week of an employee.
`ReportingPeriod` is unique on its Monday, so there is one September 7-11 for
the whole office and every contributor adds to the same one. The Division
updates the system on **Thursday**; the week is presented at the **Monday
convocation** that follows.

- **No leaderboards, and no way to build one.** `stats.py` aggregates at one
  level only - the Division - and a test in `updates/tests.py` fails if a
  figure keyed by staff member ever appears in it. The `focal_person` on an
  entry says who can answer for the item; it is never a grouping key.
- **"Weekly update completion" measures the week, not the roll.** A week is
  expected to carry seven things - activities, communications, accomplishments,
  photographs, a POPS Plan update, ways forward and what is coming - and the
  percentage is how many of them are filled in. A per-employee submission rate
  would have been the performance monitor this module is explicitly not, and
  would answer a question nobody at the convocation asks. What the Chief gets
  instead is `missing_components`: which parts of the Division's week are still
  blank.
- **An upcoming activity is not an accomplishment.** It is recorded on the same
  week, because the convocation asks for it, but it is excluded from the
  accomplishment counts - and it is the one thing allowed to carry a date after
  the week it is filed on. Anything else dated outside the week is refused, on
  the grounds that it has almost certainly been filed on the wrong one.
- **Presenting and publishing are different decisions.** The Chief selects the
  major accomplishments for the convocation on one form, and clears entries and
  photographs for the public website on another. Running both through one
  checkbox would have meant the Chief could only ever do both. A week cannot be
  published with nothing cleared.
- **The contributor's form carries neither decision.** `is_major`,
  `convocation_order` and `is_public` are absent from `DivisionUpdateForm`
  entirely - the same rule as Incoming and Documents, where the encoder records
  and the Chief decides.

**Every headline figure carries its breakdown.** A bare "14 accomplishments"
invites the next question rather than answering it, so each of the five cards
prints the parts it is made of - completed / ongoing / pending, the six ways the
Division took part, incoming against outgoing, which parts of the week are
recorded, and how soon the upcoming work falls. The parts are counted from the
*same population* as the figure above them, so they add up: activity types are
counted inside the Activities figure rather than across every category, and a
test fails if any breakdown stops summing to its headline. A sub-total that
does not sum to the number printed over it reads as a bug whatever it
technically measures.

**The grids are sized to tile.** Four of the eight charts are two columns wide
and four are one, and they are returned strictly alternating, because a
two-wide panel will not drop into the single column left at the end of a row -
grouped any other way the three-column grid ends up with holes in it. The
twenty-figure breakdown runs two, four or five across, never three, since
twenty divides by all but the third; and the five headline figures sit two
across with the fifth spanning both until all five fit. A test asserts the
chart tiling, so a ninth panel added in the wrong place fails the build rather
than leaving a gap on the page.

Four faces, one sidebar entry: the **division dashboard** (`/app/updates/`,
twenty-odd division figures and eight charts), the **reporting weeks**
(`/app/updates/weeks/`, one consolidated summary each), the **Chief's review**
(`/app/updates/weeks/<id>/review/`) and the **convocation view**
(`/app/updates/convocation/`) - typed larger because it is read from the back of
a room, and carrying no control that changes anything.

The public site gains `/accomplishments/`, which carries the same statistics
the office works from - the five headline figures, the twenty-figure breakdown
and all eight charts - **over the weeks the Chief has published and left inside
the disclosure window**. Review comes before disclosure, so a week still being
filled in contributes nothing to the public figures even if its entries are
individually ticked, and the public number is never ahead of the Division's own
reviewed record.

**The disclosure window** (`/app/updates/public-disclosure/`, `can_approve`) is
how far back the public record runs, and it is a standing decision rather than
a decision about one week. Publishing a week says it *may* be disclosed; this
says how much of the published record is on the site now - the most recent N
completed weeks (the default, eight), the last N months, a range of dates the
Chief pins exactly, or everything. Two rules hold whatever is set:

- **The week the Division is still working on is not shown.** It is a work in
  progress, not an accomplishment report. A switch on the form overrides that
  when the Chief wants the running week up.
- **The window narrows and can never widen.** Every branch starts from
  `published()`, so no setting can put an unreviewed week on the public site,
  and a fixed range missing one of its dates shows nothing rather than
  defaulting to everything - failing open would disclose the whole archive at
  the moment the Chief was trying to restrict it to one period.

A week outside the window is not merely left off a list: it 404s at its own
public address and contributes nothing to the published figures, because
`disclosed_periods()` answers "what are we showing" for the listing, the week
page and the statistics alike. The Chief's page prints the resulting list of
weeks beside the control that decides it.

A published week is laid out there exactly as it is at the convocation - the same banner, the same five
figures, the same numbered accomplishments - so the office and the public read
the Division's week in the same shape. What differs is what reaches the page.
The **figures** are the week's division totals, which is the kind of aggregate a
government office publishes about itself; the **lists** beneath them carry only
the entries, photographs, POPS Plan rows and ways forward the Chief cleared one
at a time. `stats.Scope` is what holds that distinction: it narrows the
row-level records to what was cleared and deliberately leaves the counts alone,
because a week the Division published did fourteen things whether or not all
fourteen were released one by one, and understating that would misreport the
office's own work. So the page can honestly say the Division did fourteen things while
publishing the six it chose to publish. The POPS Plan percentage is computed
from the published rows alone, so it always adds up to the table printed
beneath it. Nothing about an individual employee is published, and neither are
the Chief's remarks, whatever else is ticked.

Review and publication sit with `can_approve` - the capability that already
approves reports and publishes to the public website - rather than under a new
role. Handing the week to the Chief is `can_encode`, because saying the
Division's week is ready is the contributors' act, not the Chief's.

### Scheduling the notification digest

Standing conditions need a scheduled run. Once each working morning is enough:

```
Windows Task Scheduler:  venv\Scripts\python.exe manage.py refresh_notifications
cron:                    0 7 * * 1-5  /path/to/venv/bin/python manage.py refresh_notifications
```

Safe to run repeatedly - it deduplicates what is already known and withdraws
what has been resolved. It covers the incoming register too: documents waiting
on the Chief, assignments not yet acknowledged, documents past their action due
date, and assigned documents that have gone quiet. And the document register:
documents awaiting review, assignment or approval, documents past their action
due date, and documents whose retention period has run out or is about to.

### Eight gotchas, recorded so they are not repeated

1. `{# ... #}` is a **single-line** comment. A `{# ... #}` block spanning
   several lines is not a comment: its text is printed into the page and any
   `{% ... %}` inside it is executed. Use `{% comment %}...{% endcomment %}`.
   (An `{% include %}` inside such a block made a component include itself and
   the dashboard recursed until Python gave up; a later one leaked developer
   notes onto the audit page.) `core/tests_templates.py` now fails the build if
   one reappears.
2. **Do not `include()` a namespaced URLconf inside another namespaced
   URLconf.** The namespaces nest - `core:monitoring:list` - and every
   `{% url 'monitoring:list' %}` fails. The module URLconfs are therefore
   included at the project root in `config/urls.py`, not in `core/urls.py`.
3. **Do not decide the active sidebar item from the URL path.** `/app/`
   prefixes every module, so Dashboard lit up alongside them; and moving
   accounts to `/accounts/` lit nothing at all. `core/navigation.py` matches on
   the resolved URL's namespace instead - what the item *is*, rather than where
   it happens to sit in the URL tree.
4. **Watch for a loop variable shadowing an imported function.** `for record
   in queryset` inside `export_csv` shadowed the `record()` audit function
   imported at the top, and the export died on the line that logged it. The
   loop variable is now `item`.
5. **Do not name a context-processor variable `site`.** Django's
   `auth.views.LoginView` puts its own `site` object into the context, and a
   view's context beats a context processor - so on the sign-in page every
   `{{ site.* }}` rendered as an empty string. No error, no warning: the page
   simply lost its department name, system name and contact address, and it
   had been that way since Phase 1. The identity is published as `agency`,
   and `core/tests_templates.py` fails the build if `site.` reappears in a
   template.
6. **A test that POSTs to the sign-in form now has to say it is not about
   reCAPTCHA.** With keys configured on the machine, the check is live in the
   test run too, and a post without a token is refused - which reads as a
   mysterious authentication failure. Decorate such a test with
   `@override_settings(RECAPTCHA_SITE_KEY="", RECAPTCHA_SECRET_KEY="")`; no
   keys, no check. The three that existed already carry it.
7. **The compiled stylesheet is cache-busted in development, and needs to
   be.** `app.css` is built by hand with `build-css.ps1`, and the browser holds
   the previous copy: every newly used utility class silently does nothing - a
   hover state that never hides, a wrap that never wraps, a legend swatch that
   never appears. Nothing errors and the page looks like the edit was never
   made. `core.context_processors.asset_version` stamps the stylesheet and the
   script with their modification time when `DEBUG` is on; in production
   `ManifestStaticFilesStorage` already hashes the filename, so the stamp is
   empty. The five templates that carry their own `<head>` each apply it.
8. **Add or remove a `GovModelForm` field in `prepare_fields()`, never after
   `super().__init__()`.** The base form's styling loop reads `self.errors` so
   it can mark invalid inputs, and *reading* `errors` validates the form. A
   field popped after that has already been cleaned: the calendar's owner
   field, hidden from ordinary employees, still produced "This field is
   required" on a form that did not show it, and the save failed with no
   visible cause. `GovModelForm.prepare_fields()` runs between the fields
   being built and anything looking at them.

---

## Tests

```powershell
venv\Scripts\python manage.py test
```

370 tests covering: every public and authenticated route renders; unauthenticated
access redirects to sign-in; administration modules return 403 for
non-administrators and 200 for administrators; the role permission matrix; that
exactly one sidebar item is active (`/app/` prefixes every module URL); that
dashboard counts match the records; that the public site shows only published
records; search, filtering, whitelisted sorting and filtered CSV export; that a
viewer POSTing to a create URL is refused and no record is written; that an
encoder is recorded as the author; that overdue follow-ups are detected; and
that every status value a model defines is mapped to a colour; that a draft or
post-dated news item is invisible on the public site by every route - the feed,
the homepage and its own address; that the document library's search, type
and year filters each narrow the list; and that the Public Website page is
refused to encoders and viewers, while text saved there reaches the homepage,
the About page and the footer.

Phase 3 adds: that creates, updates and deletes are logged with field-level
diffs; that foreign keys are logged by name rather than by id; that a save
changing nothing is not an event; that entries survive the actor's deletion;
that work outside a request is not attributed to whoever signed in last; that
passwords never reach the log; that role changes, deactivations, sign-ins,
failed sign-ins and refused access are recorded; that the log offers no write
path; that an administrator cannot change their own role or deactivate
themselves; that weak and mismatched passwords are refused; that each system
setting changes what it claims to; and that a reference entry in use is
protected with an explanation rather than a 500.

Phase 4 adds: that a submitted report notifies exactly those who can approve
it and nobody else; that deactivated accounts are not notified; that the
person who acted is not told about their own action; that a standing
condition notified three times still produces one notification; that a notice
is withdrawn when the work is done; that one user cannot open, read or clear
another's queue; that coverage counts LGUs reached rather than visits made;
that turnaround averages submission to publication; that every chart's figure
table lines up with its headers; that a date range narrows a list and a
repeated filter widens it; and that exports are logged with their row count.

Phase 5 adds: that a recorded document starts unassigned and awaiting review;
that the encoder's form carries no focal-person, status or due-date field at
all; that an encoder POSTing to the assign URL is refused with 403 and no
assignment is written; that only the Division Chief may assign, and the
assignment records who decided and when; that assigning withdraws the Chief's
own review notice and notifies the focal person; that a reassignment is
recorded as such; that only the assigned person may acknowledge or update;
that an update moves the document to the status it reports; that completing
stamps the completion time and a completed document is never overdue; that a
returned document loses its completion time; that an encoder may amend a
record only until the Chief has acted on it, while the Chief may amend it at
any point; that the overdue condition is raised once, not on every run, and
withdrawn when the work is closed; that the monitoring dashboard is refused to
everyone who cannot assign; that every one of the ten reports builds against
an empty office; and that a report's CSV carries the filtered rows and nothing
else.

Phase 6 adds: that a private activity is visible to its owner and to
supervisors and to nobody else; that a team activity reaches the owner's
section and stops there; that an employee with no section is not handed every
team activity by a null matching a null; that the assigned employee sees an
activity they did not create; that guessing a primary key returns 404 on the
record, the edit form and the delete confirmation alike; that an activity a
colleague may read is still not one they may change or delete; that the
Division Chief may open any activity but is refused its edit form; that an
administrator may edit one; that an employee creating an activity owns it, and
that posting an `owner` they were never offered does not file it under a
colleague; that the section defaults to the owner's; that the assigned employee
may report progress but cannot rename or re-scope the record in the same post;
that a bystander may not report progress at all; that asking for everyone's
calendar without the capability shows your own; that the CSV export carries
only permitted activities; that a multi-day activity is not overdue on its
second morning; that the monitoring page is refused to ordinary employees and
reports each employee's workload; that the whole day box carries the link and
the day's data while remaining an ordinary link without scripting; that a busy
day caps the cell at three but hands the dialog all of them; that the day
panels shipped with the page carry nothing the viewer may not see; that an
each dialog has exactly one scroll container and no `display:flex` on the
`<dialog>` element itself; that the Save button reaches the form it sits
outside of; that the plainest calendar URL is accepted as a return address; that
a long title reaches the grid whole, so CSS rather than the server decides
where it stops; that an abbreviated start time keeps its minutes when it has
them; that the filter bar
is rendered once, above the grid rather than inside the list; that a quick add
from the day dialog is owned by whoever made it, takes its section from them
and returns to the calendar it came from; that the short form offers no way to
file under a colleague and still refuses an assignee who could not see the
result; that an invalid quick post writes nothing and comes back with its
errors; that an off-site `next` is ignored; that a viewer is offered no form
and is refused if they post one anyway; and that the
form refuses to publish a private activity or to assign one nobody but the
owner could see.

Phase 7 adds: that a control number is issued in sequence and is never
reissued after a record is removed; that a document registered through the form
is owned, numbered and given version 1; that uploading a revision keeps the file
it replaced and points the document at the new one; that a revision without a
reason is refused; that someone with no stake in a document cannot upload a
version to it; that only the Chief may name the focal person, that an encoder
POSTing to the assign URL is refused with 403 and no assignment is written, and
that assigning implies the document was read; that a reassignment is recorded as
such; that an encoder cannot approve; that completing starts the retention clock
from the document type, that a type marked permanent settles the document, and
that a type with no period leaves a visible gap rather than a silent one; that
archiving keeps the metadata, the versions and the trail and only restricts
access, and takes the document off the public website; that an unfinished
document cannot be archived and an encoder cannot archive at all; that an
archived document is refused to an unconnected user but still readable by the
people answerable for it, and is left out of the register unless asked for; that
disposal is refused unless the document is archived, marked for disposal, and
the officer is authorised - and that after it the record, its ownership, its
version list and its whole trail survive; that a view is recorded once a day per
person while every download is recorded; that a download goes through the
application and reaches the trail; that a disposed document's file cannot be
fetched; that a file missing from storage reads as 404 and records no download;
that an unacceptable file format is refused; that the retention register is
refused to everyone who cannot archive; that opening a document reaches its
trail while a request that was refused leaves no trace of having viewed it -
a trail putting a person's name against an act they did not commit is worse
than no entry at all; and one end-to-end journey driven
through the URLs the office actually uses, from registration to archive,
asserting every expected entry reached the trail.

Phase 8 adds: that a reporting week runs Monday to Friday with its deadline on
Thursday and its convocation on the following Monday; that only one week may
carry a given Monday, so contributions from different people land on one
division record; that an entry dated outside its week is refused while an
upcoming activity may be dated after it; that upcoming work is counted as
upcoming and not as an accomplishment; that every division figure the
convocation asks for is computed from the records; that no figure in the
statistics is keyed by staff member; that week completion measures the contents
of the week and names what is missing; that the review page is refused to an
encoder and opens for the Chief; that selecting an accomplishment for the
convocation does not publish it; that a week cannot be published with nothing
cleared and publishes only what was; that reopening withdraws it from the
public website; that any contributor may hand the week to the Chief; that a
viewer POSTing to the create form is refused and nothing is written; that an
encoder's contribution is neither selected nor published by the act of filing
it; that no staff name reaches either public page; that the public week carries
the Division's figures for the week while listing only what was cleared; that
the published POPS Plan percentage is computed from the published rows alone;
that the week still running is kept off the public site and 404s at its own
address until the Chief says otherwise; that each disclosure window - recent
weeks, recent months, a pinned range - selects exactly the weeks it names; that
a week outside the window 404s and drops out of the published figures with it;
that a half-filled date range shows nothing rather than everything; that no
window setting can disclose a week that was never published; that the public
statistics follow the window as it is narrowed and widened; that the control is
refused to an encoder and an encoder POSTing to it changes nothing;
that the public statistics page counts only published weeks, so an unreviewed
week contributes nothing even when its entries are ticked; that its row-level
lists are narrowed to what was cleared while its counts are not; that every
chart on it carries a figure table whose rows line up with its headers; that an
unknown reporting year falls back rather than failing; that the page stands up
with nothing published at all; and that the eight charts tile a three-column
grid into four full rows with no empty cell; that each headline card carries
the breakdown it is made of and every breakdown sums to the figure above it;
that an activity type recorded outside the activity category does not inflate
that sum; that the completion card names the parts of the week that are
missing rather than only its percentage; and that the upcoming figure splits
by how soon the work falls.

Sign-in protection adds: that a low score is refused and recorded as a failed
sign-in; that a missing token is refused without calling Google at all; that a
token minted for another action is refused; that a refused attempt never
reaches `authenticate()`; that an unreachable Google and a mistyped secret key
both let people through rather than locking them out, the second with an error
in the log; that monitor mode records the verdict and refuses nobody; that
with no keys the check is absent from both the form and the page; and that the
page carries the site key and never the secret.

---

## Before deployment

- Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` and `DJANGO_ALLOWED_HOSTS`.
  With `DEBUG=0` the settings switch on secure cookies, HSTS and
  `ManifestStaticFilesStorage`.
- Set the reCAPTCHA keys as real environment variables on the server, and
  register the production domain at <https://www.google.com/recaptcha/admin> -
  keys are per-domain, and one registered only for `localhost` verifies
  nothing in production. Leave `RECAPTCHA_ENFORCE=0` for the first week, watch
  the audit log for refusals that are real staff, then set it to 1.
- Run `manage.py collectstatic`.
- Run `manage.py seed_records --clear` and delete the `bootstrap_demo` accounts.
- Set the audit retention period in
  `audit/management/commands/prune_audit_log.py` from the office's
  records-disposition schedule, and schedule the command to run.
- Schedule `refresh_notifications` (see above), or overdue follow-ups will
  never be raised.
- Verify the LGU roster against the office's official records.
- Configure `MEDIA_ROOT` on persistent storage — documents, report files and
  monitoring attachments are uploaded there.
- The official DILG seal is in place at `static/img/dilg-logo.png`. If it is
  ever replaced, drop the new file at that path - every placement reads from
  `templates/includes/agency_logo.html`.
