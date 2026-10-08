# 8. Dashboard Guide

The **Dashboard** is the first page after sign-in (**Sidebar › Dashboard**). Every figure, chart and list on it is calculated from the records at the moment the page opens; when there is nothing to count, the panel says so.

{{figure:dashboard-overview}}

| Part | What it shows |
|---|---|
| **Summary figures** | Total Programs, Active Programs, Monitoring Activities, Registered LGUs, Pending Reports and Published Reports. **View details** under each figure opens the records it counts. |
| **Analytics charts** | Program Status, Monitoring Activities (per month), LGU Monitoring Coverage and Report Submissions. |
| **View figures** | Each chart has a **View figures** disclosure that shows the same numbers as a table — useful for printing and for screen readers. |
| **Recent Monitoring Activities** | The most recent monitoring records. **View all** opens the Monitoring register. |
| **Requires Attention** | Work waiting on the Division, for example incoming documents awaiting the Division Chief's review, overdue documents, monitoring records awaiting review, documents awaiting review and overdue follow-ups. Each line is a link to exactly those records. |
| **Upcoming Activities** | Calendar activities coming up that you are allowed to see. |

{{figure:dashboard-panels}}

### Procedure 8.1: Use the Dashboard to find work that needs attention

**Purpose:** Go straight from a figure to the records behind it.

**Who can do this:** All roles.

**Steps:**

1. Click **Dashboard** in the sidebar.
2. Scroll to **Requires Attention**.
3. Click a line, for example *Incoming documents awaiting Division Chief review*.

**Expected Result:** The module opens, already filtered to the records that were counted.

**Important Notes:** **Export reports** downloads the Reports register as a CSV file. **New monitoring record** is shown only to roles that may encode (not to Viewers).

# 9. User Roles and Access Permissions

Every account has one of five roles. The role decides which modules appear in the sidebar and which buttons appear on each page. **The system also checks permission on the server for every request**, so hiding a button is only a courtesy: an action that is not permitted is refused even if its address is typed directly.

## 9.1 The five roles

| Role | Typical holder | In short |
|---|---|---|
| **System Administrator** | Information Technology Officer | Everything an Administrator can do, plus **Menu Permissions** and editing or deleting any employee's calendar activities. |
| **Administrator** | Division Chief and designated administrators | Reviews and assigns incoming documents and registered documents; supervises the calendar; publishes PPAs; manages users, settings and the audit log; verifies e-SIRA certificates. Two-step verification is mandatory. |
| **LGMED Staff** | Technical staff | Encodes records; reviews PPAs; approves reports and the public website content; archives documents; acts as focal person on assigned documents. |
| **Encoder** | Administrative staff | Records and edits operational records (incoming documents, monitoring, documents, updates, etc.). Cannot review, assign, approve or publish. |
| **Viewer** | Read-only users | Reads the modules. No Add, Edit or Delete buttons. Can still receive, sign and act on documents routed to them in e-SIRA. |

## 9.2 Module access by role

The table below was verified by signing in with each role and opening every page.

| Module / page | System Administrator | Administrator | LGMED Staff | Encoder | Viewer |
|---|:-:|:-:|:-:|:-:|:-:|
| Dashboard | ✔ | ✔ | ✔ | ✔ | ✔ (no *New* button) |
| Programs & Projects | ✔ | ✔ | ✔ | ✔ | Read only |
| PPA Review Queue | ✔ | ✔ | ✔ | — | — |
| Publication Authorities | ✔ | ✔ | ✔ | — | — |
| Monitoring | ✔ | ✔ | ✔ | ✔ | Read only |
| Incoming Monitoring (register) | ✔ | ✔ | ✔ | ✔ | Read only |
| Incoming › Monitoring dashboard | ✔ | ✔ | — | — | — |
| Incoming › Monitoring reports | ✔ | ✔ | ✔ | ✔ | — |
| Outgoing Monitoring | ✔ | ✔ | ✔ | ✔ | Read only |
| Data Sync | ✔ | ✔ | ✔ | ✔ | — |
| LGU Management | ✔ | ✔ | ✔ | ✔ | Read only |
| Frontline Services | ✔ | ✔ | ✔ | ✔ | Read only |
| Accomplishments (entries and weeks) | ✔ | ✔ | ✔ | ✔ | Read only |
| Accomplishments › Review the week, Public disclosure | ✔ | ✔ | ✔ | — | — |
| Announcements | ✔ | ✔ | ✔ | ✔ | Read only |
| Document Management (register) | ✔ | ✔ | ✔ | ✔ | Read only |
| Document Management › Retention & Archive | ✔ | ✔ | ✔ | — | — |
| Analytics | ✔ | ✔ | ✔ | ✔ | ✔ |
| Reports | ✔ | ✔ | ✔ | ✔ | Read only |
| Calendar | ✔ | ✔ | ✔ | ✔ | Read only |
| Activity Monitoring | ✔ | ✔ | — | — | — |
| Public Website | ✔ | ✔ | ✔ | — | — |
| Users & Roles, System Settings, Audit Logs | ✔ | ✔ | — | — | — |
| Menu Permissions | ✔ | — | — | — | — |
| e-SIRA (dashboard, documents, my certificate, signature style) | ✔ | ✔ | ✔ | ✔ | ✔ (no upload) |
| e-SIRA › Certificate Verification, Audit Trail | ✔ | ✔ | — | — | — |

## 9.3 Key permissions

| Permission | Held by | What it allows |
|---|---|---|
| Encode | System Administrator, Administrator, LGMED Staff, Encoder | Create and edit operational records; upload files; submit PPAs and weekly records for review. |
| Approve | System Administrator, Administrator, LGMED Staff | Review PPAs and their files; review and publish the Division's week; manage the Public Website; archive documents. |
| Review incoming / assign documents | System Administrator, Administrator | Review incoming documents and registered documents and name the focal person. |
| Supervise | System Administrator, Administrator | See every employee's calendar activity and the Activity Monitoring page; oversee all e-SIRA documents. |
| Publish PPAs | System Administrator, Administrator | Publish, unpublish and archive PPA records and release their files. |
| Delete | System Administrator, Administrator | Delete records (always after confirmation). |
| Dispose of documents | System Administrator, Administrator | Permanently dispose of archived documents under a recorded disposal authority. |
| Administer | System Administrator, Administrator | Users & Roles, System Settings, Audit Logs, e-SIRA certificate verification. |
| Manage any calendar activity | System Administrator | Edit or delete another employee's activity. |

> **NOTE:** Some permissions depend on the record, not only on the role. For example, only the **assigned focal person** sees **Acknowledge receipt** on an incoming document, and only the recipient **whose turn it is** can sign or approve an e-SIRA document. The Division Chief can *read* every calendar activity but cannot *edit* another employee's activity.

The live permission matrix is always available to administrators at **Users & Roles › Roles & permissions** (Figure {{ref:users-roles}}). It is generated from the same rules the system enforces, so it cannot be out of date.
