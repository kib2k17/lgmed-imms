# 11. Common Tasks and Procedures

These procedures work the same way in every module.

### Procedure 11.1: Search and filter any list

1. Open the module from the sidebar.
2. Type in the search box and/or choose values in the filter drop-downs. Where a date range is offered, enter **From** and **To** (and, where asked, which date the range applies to).
3. Click **Apply**.
4. To start again, open the module from the sidebar (or click **Clear** where offered).

**Expected Result:** Only matching records are listed; the page title area shows the number of results.

### Procedure 11.2: Export a list to a spreadsheet (CSV)

1. Search and filter the list until it shows the records you need.
2. Click **Export CSV** (or **Export reports** on the Dashboard).
3. Open the downloaded `.csv` file in Excel.

**Important Notes:** The file contains exactly the rows on screen (all pages), with the same filters. Each export is written to the audit log with the number of rows. Treat exported files as official records: store them securely and delete them when no longer needed.

### Procedure 11.3: Print a record or report

1. Open the record, report or monitoring page.
2. Click **Print**.
3. Choose the printer (or *Save as PDF*) in the browser's print window.

**Expected Result:** A print-friendly version without the sidebar and buttons is printed.

### Procedure 11.4: Attach a file

1. Open the record and find its attachment panel (**Supporting Documents**, **Means of Verification**, **Document File**, etc.).
2. Choose the file, complete the required fields (title, type) and click the panel's button (**Attach**, **File the evidence**, **Upload version**, **Upload and screen**).

**Important Notes:** See Section 13.2 for file types and sizes.

### Procedure 11.5: Delete a record

1. Open the record (or use the bin icon on its row).
2. Click **Delete**.
3. Read the confirmation and click the red delete button, or **Cancel**.

**Important Notes:** Only Administrators can delete. Deletion cannot be undone. Where the module offers **Archive**, **Cancel** or **Deactivate**, use that instead so the history is kept.

# 12. Notifications and Alerts

LGMED-iMMS tells you about work in four ways:

| Kind | Where you see it | Examples |
|---|---|---|
| **Notifications** | The bell in the top bar and the **Notifications** page (Section 10.2) | Document awaiting review; incoming document assigned to you; document overdue; follow-up overdue; document completed; report awaiting approval. |
| **Confirmation messages** | A coloured message at the top of the page after you act | *Signed in as …*; record saved; record deleted. |
| **System notice** | A banner on every page (or, when urgent, a full-screen notice with an alert sound), set by the administrator in **System Settings** | Scheduled maintenance. |
| **Session warning** | A dialog shortly before your session expires | Save your work, then continue or sign in again. |

**Notification categories:** Awaiting review, Overdue, Awaiting publication, Assigned to you, Account, System.
**Priority levels:** Information, Needs action, Urgent.

How notifications behave:

- They are addressed to **you personally**, so the unread count means *things you have not yet dealt with*.
- Two kinds exist. **Event** notifications are raised when something happens (for example, a document is assigned to you). **Standing** notifications are raised for conditions that persist (for example, a follow-up past its due date); these are refreshed by a scheduled task each working morning.
- A standing problem is notified **once**, not every day.
- A notification **withdraws itself** when the work is done.
- You are not notified about your own actions, and deactivated accounts are not notified.

> **NOTE:** If overdue items never seem to produce notifications, the scheduled refresh may not be running on the server. Report this to the system administrator.

# 13. Data Validation and Error Handling

## 13.1 Form validation

When a form cannot be saved, it is shown again with:

- a summary at the top, and
- the reason in red under each field that needs attention.

Your entries are kept, so correct only what is marked and click **Save** again.

| Rule | Where it applies |
|---|---|
| Fields marked **\*** must be filled in. | All forms |
| Dates must be valid, and an end date cannot be before its start date. | Calendar, programs, accomplishments, disclosure window |
| An accomplishment's date must fall inside its reporting week (except **Upcoming** entries). | Accomplishments |
| Review comments are required when requesting revision or rejecting. | PPA review |
| A reason is required for a new document version, archiving, restoring, cancelling, returning for revision and cancelling an e-SIRA document. | Document Management, Outgoing, e-SIRA |
| **DISPOSE** must be typed to confirm a disposal, and a disposal authority chosen. | Document Management |
| A private activity cannot be shown on the public calendar, and cannot be assigned to someone who could not see it. | Calendar |
| A week cannot be published with nothing cleared. | Accomplishments |
| Passwords must be strong and must match. | Users & Roles |
| Records per page 5–100; session warning 1–60 minutes. | System Settings |

## 13.2 File uploads

| Where | Accepted types | Maximum size |
|---|---|---|
| Programs & Projects supporting documents | PDF, DOC/DOCX, XLS/XLSX, PPT/PPTX, JPG/JPEG, PNG | 25 MB |
| Document Management, Outgoing communications | PDF, DOC/DOCX, XLS/XLSX, CSV, PPT/PPTX, JPG/JPEG, PNG, GIF, BMP, WebP, TIF/TIFF | 25 MB |
| e-SIRA documents | PDF, or scanned page images | 25 MB |
| Accomplishment evidence (photographs) | JPG/JPEG, PNG, WebP, GIF (a *Photograph* must be an image) | — |
| Announcement photographs | JPG/JPEG, PNG, WebP, GIF | — |
| Profile photo | JPEG, PNG, WebP | 5 MB |
| e-SIRA signature image | PNG, JPG | 2 MB |
| e-SIRA certificate | .p12 / .pfx | — |
| Data Sync | Excel workbook (.xlsx) | — |

A file of the wrong type or too large is refused with a message under the field.

## 13.3 Error pages

| Page | Meaning | What to do |
|---|---|---|
| **Access denied (403)** | Your role, or the menu permissions, do not allow this page or action. | Use the sidebar. If you need access, ask an administrator. |
| **Page not found (404)** | The address is wrong, or the record does not exist or is not visible to you (for example, another employee's private calendar activity). | Check the address; return through the sidebar. |
| **Server error (500)** | An unexpected fault. | Note the time and what you were doing, and report it to the system administrator. |
| **Bad request (400)** | Usually an address the server does not recognise. | Use the address the administrator gave you. |
| **Maintenance notice** (public website) | The public website has been switched off by the administrator. | Staff sign-in still works at `/staff`. |

{{figure:errors-403}}

# 14. Frequently Asked Questions

**I cannot see a module that a colleague can see.**
The sidebar shows only the modules your role permits, and the System Administrator can close modules to a role or account. Ask an administrator if you need it.

**Why is there no Edit or Add button for me?**
Your role is read-only for that module (for example, Viewer), or the record has moved past the stage you may change (for example, an encoder can amend an incoming document only until the Division Chief acts on it).

**As an encoder, how do I assign a focal person?**
You cannot; naming the focal person is the Division Chief's decision. Record the document and the Chief is notified.

**I was assigned a document. Where do I report what I did?**
Acknowledge it on the incoming record (**Acknowledge receipt**), then report your action on its **Outgoing Monitoring** record with **Record update**.

**I recorded the communication sent, but the document is still open.**
Recording the communication does not close it. Record an update with the status **Completed**.

**Why does my week say parts are missing?**
A week is expected to have activities, communications, accomplishments, a means of verification, a POPS Plan update, ways forward and upcoming activities. **The Division's Week** panel lists what is still blank.

**I ticked an entry for the public website, but it is not on the site.**
An item is public only when it is cleared **and** its week is published **and** the week is inside the public disclosure window.

**Why can the Division Chief see my private calendar activity?**
Supervisors (Administrators) can read every activity so they can monitor the office's workload. They cannot change it.

**I lost my phone and cannot sign in.**
Use one of your recovery codes. If you have none, ask an administrator to **Reset two-step verification** on your account.

**Why can I not sign in e-SIRA documents?**
You need a registered PNPKI certificate that an administrator has verified, and it must be your turn on the route.

**Can a deleted record be recovered?**
No. Deletion is permanent, which is why only Administrators can delete and why archiving, cancelling and deactivating are offered instead.

**Does the system keep my records on my phone when installed as an app?**
No. Only the screen design and an offline notice are stored on the device.

# 15. Troubleshooting Guide

| Problem | Possible cause | What to do |
|---|---|---|
| The sign-in page does not open. | Wrong address; not on the office network; server not running. | Check the address with `/staff`; confirm you are connected to the office network; contact the system administrator. |
| *Sign-in unsuccessful.* | Wrong username or password; Caps Lock on; account deactivated. | Retype carefully (use the eye button); check Caps Lock; ask an administrator to reset your password or reactivate your account. |
| Sign-in is refused even with the correct password, or a notice says JavaScript is off. | JavaScript disabled, or the browser cannot reach Google for the sign-in security check. | Switch JavaScript on; try another browser; report to the administrator if the office network blocks `www.google.com`. |
| The authentication code is rejected. | Phone clock wrong; code expired; wrong account in the app. | Set the phone's time automatically; type the newest code; use a recovery code; ask an administrator to reset two-step verification. |
| I am signed out unexpectedly. | The browser was closed, or the session expired after inactivity. | Sign in again. Save work when the session warning appears. |
| The Privacy Notice keeps appearing. | The notice has not been accepted, or it was updated. | Tick the agreement box and click **I Agree and Continue**. |
| *Access denied* on a page. | Not permitted for your role or by menu permissions. | Use the sidebar; ask an administrator if you need access. |
| A record I expect is not in the list. | A filter, search or date range is still applied; archived records are hidden; it is not visible to you. | Clear the search and filters; choose **View: Archived** where applicable; check with the record's owner. |
| A file will not upload. | Wrong type or too large. | Check Section 13.2; reduce or convert the file. |
| A PDF does not display. | The browser blocked the viewer, or the file is damaged. | Download the file instead; try Chrome or Edge. |
| Charts show no data. | There are no records for the chosen year. | Change the **Year**. The panel says so when there is nothing to count. |
| An export opens with strange characters in Excel. | Excel's default text encoding. | Open Excel › **Data › From Text/CSV** and choose UTF-8. |
| *Install app* is not in the account menu. | The browser cannot install the site, or the address is not HTTPS. | Use Chrome or Edge on the system's HTTPS address. |
| e-SIRA refuses to sign. | No verified certificate; wrong password; certificate expired; not your turn; PNPKI roots not installed on the server. | Check **My Digital Certificate**; ask an administrator to verify; check **Waiting on Me**; report persistent errors. |
| Overdue items raise no notifications. | The scheduled notification refresh is not running. | Report to the system administrator. |

# 16. Security, Privacy, and Good Practices

LGMED-iMMS holds personal information about local government officials, focal persons and DILG personnel. Every user is bound by the **Data Privacy Act of 2012 (Republic Act No. 10173)** and the notice accepted at first sign-in.

**Your account**

- Never share your username, password, authentication codes or recovery codes. Nobody from the office will ask for them.
- Use a strong password that you do not use elsewhere.
- Set up two-step verification (mandatory for Administrators).
- Sign out when you leave your computer, and always on shared computers.
- Keep your e-SIRA certificate file and password private, and leave **Require .p12 password when signing** switched on.

**Records**

- Access and use records only as your official duties require.
- Check every file before uploading it, especially anything intended for the public website. The automated screening helps but is **not** a guarantee: *Low risk* means nothing was found.
- Clear items for the public website deliberately; never tick public options by habit.
- Prefer **Archive**, **Cancel** or **Deactivate** to deletion.
- Store exported and printed records securely and dispose of them properly.

**Accountability**

- Every sign-in, failed sign-in, change, export, download and refused access is recorded with the person's name and the time. The audit log cannot be edited from the system.
- Report any suspected data breach, loss or unauthorised access to the system administrator at once.

# 17. Glossary of Terms

| Term | Meaning |
|---|---|
| **Audit log / audit trail** | The permanent record of who did what and when. |
| **Archive** | To close a record and restrict access to it, without deleting it. |
| **Breadcrumb** | The path shown above the page title, for example *Dashboard › Incoming Monitoring*. |
| **Card / panel** | A boxed section of a page with its own heading. |
| **Control number** | The unique number the Document register gives each document (for example LGMED-2026-0010). |
| **Convocation** | The Monday meeting at which the Division's week is presented. |
| **CSV** | Comma-separated values: a plain spreadsheet file that opens in Excel. |
| **Data Sync** | Importing records from the Incoming and Outgoing Excel registers. |
| **Disclosure window** | How much of the published Accomplishments record the public website shows. |
| **Disposal authority** | A board resolution or approved records disposal schedule that authorises destroying archived documents. |
| **DNS / DMS number** | The office's document numbering reference for a received or sent document. |
| **Docket Number** | The key column of the Incoming spreadsheet register. |
| **e-SIRA** | Electronic Signature, Identification, Routing and Approval. |
| **Encoder** | The role that records data but does not review, assign, approve or publish. |
| **Focal person** | The officer assigned to act on a document. |
| **LGMED** | Local Government Monitoring and Evaluation Division. |
| **LGMED code** | The tracking code an acknowledged document carries in Outgoing Monitoring (for example LGMED-13 - RM - 2026-10-08-0004). |
| **LGU** | Local Government Unit: a province, city or municipality. |
| **Means of verification (MOV)** | Evidence that an accomplishment happened: a photograph, issuance, report, certificate, attendance sheet or letter. |
| **MFA / two-step verification** | Signing in with a password **and** a code from an authenticator app. |
| **Organizational Outcome** | One of the Department's five outcomes under which PPAs are organised. |
| **PAdES** | The standard for digital signatures inside PDF files used by e-SIRA. |
| **PNPKI** | Philippine National Public Key Infrastructure, operated by DICT, which issues the digital certificates used to sign. |
| **POPS Plan** | Peace and Order and Public Safety Plan. |
| **PPA** | Programs, Projects and Activities. |
| **PWA / Install app** | Installing the web system as an app on a computer or phone. |
| **Publication authority** | A memorandum that authorises releasing PPA files to the public. |
| **Recovery code** | A one-time code for signing in if your phone is unavailable. |
| **Reporting week** | One week of the Division's Updates & Accomplishments (Monday to Friday; updated Thursday; presented the following Monday). |
| **Retention period** | How long a document must be kept, set by its document type. |
| **Role** | The set of permissions given to an account: System Administrator, Administrator, LGMED Staff, Encoder or Viewer. |
| **Screening** | The automated check of uploaded PPA files for personal or confidential information. |
| **Signature box** | A rectangle on a PDF page showing where a person will sign; it is not itself a signature. |
| **Status** | The stage a record has reached in its workflow. |

# 18. Appendices and Reference Materials

## Appendix A. Page addresses

| Page | Address |
|---|---|
| Staff sign-in | `/staff` (opens `/accounts/login/`) |
| Dashboard | `/app/` |
| My Profile | `/accounts/profile/` |
| Notifications | `/app/notifications/` |
| Programs & Projects; Review Queue; Publication Authorities | `/app/programs/`; `/app/programs/queue/`; `/app/programs/authorities/` |
| Monitoring | `/app/monitoring/` |
| Incoming Monitoring; dashboard; reports | `/app/incoming/`; `/app/incoming/dashboard/`; `/app/incoming/reports/` |
| Outgoing Monitoring | `/app/outgoing/` |
| Data Sync | `/app/sync/` |
| LGU Management | `/app/lgus/` |
| Frontline Services | `/app/services/` |
| Accomplishments; entries; weeks; convocation; disclosure | `/app/updates/`; `/app/updates/entries/`; `/app/updates/weeks/`; `/app/updates/convocation/`; `/app/updates/public-disclosure/` |
| Announcements | `/app/announcements/` |
| Document Management; monitoring; files; retention | `/app/documents/`; `/app/documents/monitoring/`; `/app/documents/files/`; `/app/documents/retention/` |
| Analytics | `/app/analytics/` |
| Reports | `/app/reports/` |
| Calendar; Activity Monitoring | `/app/calendar/`; `/app/calendar/monitor/` |
| Public Website | `/app/settings/public-site/` |
| Users & Roles; Roles & Permissions; Menu Permissions | `/accounts/users/`; `/accounts/roles/`; `/accounts/menu-permissions/` |
| System Settings; Audit Logs | `/app/settings/`; `/app/audit-logs/` |
| e-SIRA | `/app/esira/` |
| Public website | `/`, `/announcements/`, `/accomplishments/`, `/programs/`, `/services/`, `/statistics/`, `/reports/`, `/documents/`, `/calendar/`, `/about/`, `/contact/` |

## Appendix B. Status reference

| Module | Statuses, in order |
|---|---|
| Monitoring | Scheduled → In progress → For review → Completed (or Cancelled) |
| Incoming Monitoring | For Division Chief review → Assigned → Acknowledged → In progress / For action / Pending → Completed (or Returned / for revision) |
| Document Management | Draft / Received → For review → For assignment → Assigned → In progress → For approval → Completed → Archived (or Cancelled) |
| Programs & Projects (publication) | Draft → For review (→ Screening → Review required) → Approved → Published → Unpublished → Archived |
| Reports | Draft → Submitted → For review → Approved → Published (or Returned) |
| Calendar | Planned → In progress → Completed (or Postponed, Cancelled) |
| Reporting weeks | Open for contributions → For the Chief's review → Reviewed → Published |
| Division update entries | Completed, Ongoing, Pending, Upcoming |
| e-SIRA | Draft → Awaiting Signature / Out for Signature / Routed → Partially Signed → Fully Signed / Routing Completed → Completed (or Rejected, Cancelled) |

## Appendix C. Where to get help

| Need | Contact |
|---|---|
| Account, password, two-step verification, access to a module | The LGMED-iMMS system administrator |
| Correcting your account details | **My Profile › Request a correction** |
| A suspected data breach or unauthorised access | The system administrator, immediately |
| Technical installation, backups, configuration | Project `README.md` and `docs/` (technical staff) |
