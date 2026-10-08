## 10.12 Document Management

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Document Management** (`/app/documents/`) with four tabs: **Register**, **Monitoring**, **Files**, **Retention & Archive** |
| Purpose | The Division's document register: every document received, created, submitted or processed, traceable from registration to archive and, where authorised, disposal. Documents from Incoming and Outgoing Monitoring are filed here automatically. |
| Who | **Register and process**: Encoder, LGMED Staff, Administrators (the owner or focal person acts on their own documents). **Review**: LGMED Staff and Administrators. **Assign the focal person**: Administrators (Division Chief). **Approve and complete, archive and restore, retention decisions**: LGMED Staff and Administrators. **Dispose permanently, delete**: Administrators. Viewers read only. |
| Statuses | Draft, Received, For review, For assignment, Assigned, In progress, For approval, Completed, Archived, Cancelled. |
| Retention decisions | Within retention period, For retention review, For disposal, Permanent preservation. |

### B. Visual interface guide

{{figure:documents-list}}

{{figure:documents-detail}}

**Lifecycle actions.** The **Actions** panel shows only the next step that fits the document's current status:

| Current status | Button | Who | Result |
|---|---|---|---|
| Draft or Received | **Submit for review** | Owner / editors | For review |
| For review | **Mark reviewed** (with review notes) | LGMED Staff, Administrators | For assignment |
| For review or For assignment | **Assign** in **Review and Assignment** | Administrators | Assigned |
| Assigned | **Start processing** | Owner / focal person | In progress |
| In progress | **Submit for approval** | Owner / focal person | For approval |
| For approval | **Approve and complete** | LGMED Staff, Administrators | Completed (the retention period starts) |
| Completed | **Archive document** | LGMED Staff, Administrators | Archived |
| Archived | **Restore from archive** | LGMED Staff, Administrators | Back in the register |
| Archived and marked *For disposal* | **Dispose permanently** | Administrators | Files destroyed; record and trail kept |
| Any open status | **Cancel document** | Owner / editors | Cancelled |

> **NOTE:** Documents that came from Incoming or Outgoing Monitoring show no lifecycle buttons here: their action is taken in those modules.

### C. Procedures

### Procedure 10.12.1: Register a document

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Click **Document Management › Register Document**.
2. Under **Document Information**, enter the **Document title\***, choose the **Document type\***, and enter the **Document / reference / control number**, **Subject** and **Sender / source** as applicable.
3. Under **Dates**, enter the **Date received**, **Date of document**, **Action due date** and **Year**.
4. Under **Ownership and Unit**, choose the **Owner / responsible personnel\***, the **Division / unit** and the **Office / division\***.
5. Under **File and Details**, choose the **Document file** and add a **Description** and **Remarks**.
6. Click **Save**.

**Expected Result:** The document is registered with a control number (for example *LGMED-2026-0010*) and its file becomes **version 1**.

**Visual Reference:** Figure {{ref:documents-new}}.

**Important Notes:** To offer a completed document in the public **Document Library**, edit it and tick **Available on the public website**. Accepted files: PDF, Word, Excel, CSV, PowerPoint and images (JPG, PNG, GIF, BMP, WebP, TIFF), up to 25 MB. Control numbers are never reused, even if a document is deleted.

{{figure:documents-new}}

### Procedure 10.12.2: Review and assign a document

**Who can do this:** Review: LGMED Staff and Administrators. Assign: Administrators (Division Chief).

**Steps:**

1. Open a document with the status **For review** (Monitoring tab › *For review*, or **View: Not yet assigned**).
2. In **Actions**, enter **Review notes** and click **Mark reviewed**. The status becomes **For assignment** and the Division Chief is notified.
3. In **Review and Assignment › Assign a focal person**, choose the **Assigned personnel / focal person**, enter the **Instructions** and **Action due date**, and click **Assign** (or **Reassign** later).

**Expected Result:** The status becomes **Assigned** and the focal person is notified. The **Document Trail** records the review and assignment.

**Visual Reference:** Figure {{ref:documents-assign}}.

{{figure:documents-assign}}

### Procedure 10.12.3: Process a document to completion

**Who can do this:** The owner or assigned focal person; approval by LGMED Staff or Administrators.

**Steps:**

1. Open the document assigned to you (**View: Assigned to me**).
2. Click **Start processing**.
3. Do the work. To replace the file, use **Document File › Upload a new version**: choose the **New version of the document**, give the **Reason for revision** (required), and click **Upload version**.
4. Click **Submit for approval**.
5. The approver opens the document and clicks **Approve and complete**.

**Expected Result:** The status becomes **Completed** and the retention period starts from the document type's schedule.

**Important Notes:** A file is never overwritten: earlier versions stay in **Version history** with the reason they were replaced.

### Procedure 10.12.4: View or download a file

**Who can do this:** Anyone who may see the document.

**Steps:** Open the document and, in **Document File**, click the view (PDF) or download button; earlier versions are under **Version history**. The **Files** tab (Figure {{ref:documents-files}}) lists every stored file with its **Source** (Incoming document, Focal person's update, Outgoing communication, Registered here).

**Expected Result:** The PDF opens in the viewer, or the file downloads.

**Important Notes:** Every download is recorded on the document's trail; viewing is recorded once a day per person.

{{figure:documents-files}}

### Procedure 10.12.5: Monitor documents

**Who can do this:** All roles that can see the register.

**Steps:** Click the **Monitoring** tab. Review **Document counts**, **By lifecycle stage**, **Awaiting action**, **Overdue documents**, **Retention**, **Documents by owner** and **By document type**. Click any figure to open the documents it counts.

{{figure:documents-monitoring}}

### Procedure 10.12.6: Record a retention decision

**Who can do this:** LGMED Staff, Administrators.

**Steps:**

1. Open the document and scroll to **Retention › Record a retention decision**.
2. Check or change **Retention period ends**, choose the **Retention decision\*** and add **Notes**.
3. Click **Save decision**.

**Expected Result:** The decision is shown on the document and in **Retention & Archive**.

### Procedure 10.12.7: Archive and restore a document

**Who can do this:** LGMED Staff, Administrators.

**Steps:**

1. Open a **Completed** document and click **Archive document** in **Actions**.
2. Enter the **Reason for archiving** and click **Archive document**.
3. To bring it back, open it from **Retention & Archive › Browse the archive**, click **Restore from archive**, give the **Reason for restoring**, and click **Restore document**.

**Expected Result:** Archived documents leave the working register and the public website; nothing is deleted.

**Visual Reference:** Figure {{ref:documents-archive}}.

{{figure:documents-archive}}

{{figure:documents-retention}}

### Procedure 10.12.8: Dispose of a document permanently

**Who can do this:** Administrators.

**Before you start:** The document must be **archived**, its retention decision must be **For disposal**, and the **disposal authority** (board resolution or approved records disposal schedule) must already be recorded in **System Settings › Disposal authorities**.

**Steps:**

1. Open the archived document and click **Dispose permanently**.
2. Choose the **Disposal authority**, add **Disposal notes**, and type **DISPOSE** in the confirmation box.
3. Click **Dispose permanently**.

**Expected Result:** The document's files are destroyed. The record, its ownership, its version list and its complete trail are kept as proof of the disposal.

**Important Notes:** **WARNING:** Disposal is the only irreversible action in the module. The files cannot be recovered.

### D. Workflow

{{diagram:documents}}

## 10.13 Analytics

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Analytics** (`/app/analytics/`) |
| Purpose | Performance analysis for the year: headline figures, Monitoring by Province, LGU Compliance, Monitoring Trend, Coverage by LGU Type, Programs by Category, Report Pipeline, and **Least-Monitored LGUs**. |
| Who | All roles. |

{{figure:analytics-page}}

### Procedure 10.13.1: Analyse a year and act on the least-monitored LGUs

**Steps:**

1. Click **Analytics**. Choose the **Year**.
2. Read each chart; open **View figures** under a chart to see its numbers as a table.
3. Scroll to **Least-Monitored LGUs**, which lists the LGUs the Division has reached least, in the order it should reach them.
4. Click **Schedule monitoring for …** to start a monitoring record (roles that may encode).
5. Use **Export CSV** or **Print** as needed.

{{figure:analytics-least}}

## 10.14 Reports

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Reports** (`/app/reports/`) |
| Purpose | Monitoring and evaluation reports, their files, and their review status. Published reports appear on the public website's **Reports** page. |
| Who | All roles can view. Encoder, LGMED Staff and Administrators can add and edit. Administrators can delete. |
| Statuses | Draft, Submitted, For review, Approved, Published, Returned. |

{{figure:reports-list}}

### Procedure 10.14.1: Add a report

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Click **Reports › Add Report**.
2. Under **Report Information**, enter the **Report title\***, **Reference number**, **Reporting period\***, **Year\***, **Program** and **Summary**.
3. Under **Submission**, enter **Prepared by**, attach the **File**, and choose the **Status\***.
4. Click **Save**.

**Expected Result:** The report is listed with its status. Submitting a report for review notifies those who can approve it.

{{figure:reports-new}}

### Procedure 10.14.2: Move a report through review

**Steps:** Open the report (Figure {{ref:reports-detail}}), click **Edit**, change the **Status** (for example from *For review* to *Approved* or *Returned*, then *Published*), add review remarks where offered, and click **Save**. The **Review Workflow** panel shows the stage reached.

**Important Notes:** The system notifies approvers when a report is submitted and withdraws that notice once it is approved.

{{figure:reports-detail}}

## 10.15 Calendar and Activity Monitoring

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Calendar** (`/app/calendar/`); **Activity Monitoring** (`/app/calendar/monitor/`, supervisors) |
| Purpose | Each employee's work plan. Every activity has an **owner** (whose activity it is) and may be **assigned to** someone else who carries it out. The owner decides who may see it. |
| Who | Everyone except Viewers can add activities. The owner edits and deletes their own activities; the assignee can report progress. Administrators (Division Chief) can see everyone's activities and the Activity Monitoring page but **cannot edit** another employee's activity; only the System Administrator can. |
| Visibility | **Private** (default), **Assigned users**, **Team** (the owner's section), **Organization-wide**. |
| Statuses | Planned, In progress, Completed, Postponed, Cancelled. |

### B. Visual interface guide

{{figure:calendar-month}}

**Scope and period.** *Scope* asks **whose** activities: **My calendar**, **Assigned to me**, **Shared with me**, **All employees** (supervisors). *Period* asks **over what stretch**: **Month**, **Week**, **Upcoming**, **Overdue**. They can be combined with the filters (Employee, Division / section, Type, Status, Priority).

### C. Procedures

### Procedure 10.15.1: Add an activity from a day on the calendar

**Who can do this:** Everyone except Viewers.

**Steps:**

1. Click **Calendar**. Click anywhere inside a day box (not on an existing activity).
2. The day dialog lists what is already on that day and shows a short form with the date filled in.
3. Enter the **Title\***, **Activity type\***, **Assigned to** (if someone else will do it), **Start date\*** (already filled in), **End date**, times, **Location**, **Priority\***, **Visibility\*** and **Description**. **More options** opens the full form instead.
4. Click **Save activity**.

**Expected Result:** The activity appears on that day. You are its owner.

**Visual Reference:** Figure {{ref:calendar-day}}.

{{figure:calendar-day}}

### Procedure 10.15.2: Add an activity with the full form

**Steps:**

1. Click **Calendar › Add Activity**.
2. Complete **Activity** (Title\*, Activity type\*, Description), **Ownership** (Assigned to, Department / division / section), **Schedule** (Start date\*, End date, times), **Venue and Participants** (Location, LGU concerned, Participants), **Tracking** (Priority\*, Status\*, Remarks) and **Visibility** (Visibility\*, **Show on the public calendar**).
3. Click **Save**.

**Expected Result:** The activity is saved and shown to the people its visibility allows.

**Visual Reference:** Figure {{ref:calendar-new}}.

**Important Notes:** An **Activity owner** field is shown only to administrators, who may file an activity for another employee; everyone else is automatically the owner. **Show on the public calendar** is accepted only for **Organization-wide** activities. You cannot assign an activity to someone who would not be able to see it.

{{figure:calendar-new}}

### Procedure 10.15.3: Report progress on an activity

**Who can do this:** The owner and the assigned employee.

**Steps:** Open the activity; under **Report progress**, choose the **Status**, add **Remarks** and click **Save update**.

**Expected Result:** The status changes. The assignee can report progress but cannot change the date, venue or visibility.

{{figure:calendar-detail}}

### Procedure 10.15.4: Monitor the office's workload (supervisors)

**Who can do this:** Administrators (Division Chief), System Administrator.

**Steps:** Click **Activity Monitoring**. Review **Workload by employee**, **Running today**, **By division / section**, **Planned ahead** and **Overdue**. Click a figure or **Calendar of …** to see the activities behind it; **Export CSV** downloads them.

{{figure:calendar-monitor}}
