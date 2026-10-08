## 10.4 Monitoring

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Monitoring** (`/app/monitoring/`) |
| Purpose | Record each monitoring activity conducted in an LGU: the team, the date, the findings, recommendations and the follow-up action with its due date, plus supporting documents. |
| Who | All roles can view. Encoder, LGMED Staff and Administrators can add and edit. Only Administrators can delete. |
| Statuses | Scheduled, In progress, For review, Completed, Cancelled. |
| Actions | Search, filter (Province, LGU type, Status, Year), sort, export CSV, add, view, edit, print, attach documents, delete. |

### B. Visual interface guide

{{figure:monitoring-list}}

{{figure:monitoring-detail}}

### C. Procedures

### Procedure 10.4.1: Find a monitoring record

**Purpose:** Locate records by LGU, activity, team, status or year.

**Who can do this:** All roles.

**Steps:**

1. Click **Monitoring** in the sidebar.
2. Type in the search box (marker 4 of Figure {{ref:monitoring-list}}), for example the LGU name.
3. Choose filters such as **Province**, **LGU type**, **Status** or **Year** (marker 5).
4. Click **Apply** (marker 6).
5. Click a column heading such as **LGU** or **Date** to sort (marker 7).

**Expected Result:** The list shows only matching records, in the chosen order.

### Procedure 10.4.2: Record a monitoring activity

**Purpose:** Add a new monitoring record.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Click **Monitoring › New Monitoring Record** (or **New monitoring record** on the Dashboard).
2. Under **Activity Details**, enter **Activity\***, optional **Reference number**, choose **LGU\*** and optional **Program**, and enter **Monitoring date\*** and **Monitoring team\***.
3. Under **Findings and Recommendations**, enter the **Findings** and **Recommendations**.
4. Under **Follow-up**, enter the **Follow up action** and **Follow-up due date**, and choose the **Status\***.
5. Click **Save**.

**Expected Result:** The record opens with a success message and appears in the register, in the LGU's **Monitoring History**, and on the Dashboard.

**Visual Reference:** Figure {{ref:monitoring-new}}.

**Important Notes:** When the follow-up due date passes and the record is not completed, the system raises a *Follow-up overdue* notification.

{{figure:monitoring-new}}

### Procedure 10.4.3: Edit, print or attach a document to a monitoring record

**Who can do this:** Edit and attach: Encoder, LGMED Staff, Administrators. Print: all roles.

**Steps:**

1. Open the record (click the LGU name or the eye icon).
2. To change it, click **Edit** (marker 3 of Figure {{ref:monitoring-detail}}), change the fields and click **Save**.
3. To attach a file, go to **Supporting Documents › Attach a document**, enter a **Title\***, choose the **File\*** and click **Attach**.
4. To print, click **Print** (marker 2).

**Expected Result:** Changes are saved and recorded in **Record Information** and the audit log; attached files are listed under **Supporting Documents**.

### Procedure 10.4.4: Delete a monitoring record

**Who can do this:** Administrators.

**Steps:**

1. Open the record and click **Delete** (marker 4).
2. Read the confirmation and click **Delete Record**, or **Cancel** to keep it.

**Expected Result:** The record is removed and the register is shown with a confirmation message.

**Visual Reference:** Figure {{ref:monitoring-delete}}.

**Important Notes:** **WARNING:** Deletion is permanent. The deletion itself is recorded in the audit log.

{{figure:monitoring-delete}}

## 10.5 Incoming Monitoring

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Incoming Monitoring** (`/app/incoming/`) with three tabs: **Documents**, **Monitoring dashboard**, **Monitoring reports** |
| Purpose | Register correspondence received by the Division and follow it from receipt to completion: the encoder records it; the Division Chief reviews it, notes what it requires and names the focal person; the focal person acknowledges and acts on it. |
| Who | **Record**: Encoder, LGMED Staff, Administrators. **Review and assign**: Administrators (the Division Chief). **Acknowledge and report action**: the assigned focal person. **Monitoring dashboard**: Administrators. **Monitoring reports**: everyone except Viewers. **Delete**: Administrators. Viewers read only. |
| Statuses | For Division Chief review, Assigned, Acknowledged, In progress, For action, Pending, Returned / for revision, Completed (and *Imported from spreadsheet* for records brought in by Data Sync). A document past its action due date and not completed is shown as **Overdue**. |

### B. Visual interface guide

{{figure:incoming-list}}

### C. Procedures

### Procedure 10.5.1: Record an incoming document

**Purpose:** Register a document as soon as it is received.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Click **Incoming Monitoring** in the sidebar, then **Record Incoming Document**.
2. Under **Document Details**, enter the **DNS number\*** (the office's own reference, e.g. 2026-0417), **Subject\***, **Document type\***, **Date received\*** (today by default) and **Source / office\*** (the office, agency or LGU it came from).
3. Under **Attachment and Remarks**, attach the scanned document in **Document / file attachment** and add any **Initial remarks**.
4. Click **Save**.

**Expected Result:** The record opens with the status **For Division Chief review** and no focal person. The Division Chief is notified that a document is waiting.

**Visual Reference:** Figures {{ref:incoming-new}} and {{ref:incoming-recorded}}.

**Important Notes:** The encoder's form has no focal-person field: naming the focal person is the Division Chief's decision. An encoder may amend the record (**Edit**) only until the Chief has acted on it.

{{figure:incoming-new}}

{{figure:incoming-recorded}}

### Procedure 10.5.2: Review an incoming document and assign a focal person

**Purpose:** Record what the document requires and decide who handles it.

**Who can do this:** Administrators (Division Chief).

**Steps:**

1. Open the document (Dashboard › *Requires Attention*, the notification, or **Incoming Monitoring** with **View: For Division Chief review**).
2. In **Division Chief's Review**, type **Notes / instructions\*** and click **Save review notes**.
3. In **Assignment › Assign a focal person**, choose the **Focal person\***, the **Priority\*** (Low, Normal, High, Urgent), the **Action due date** and any **Assignment remarks / instructions**.
4. Click **Assign and notify**.

**Expected Result:** The status becomes **Assigned**, the focal person receives a notification, and the **Audit Trail** on the record shows who assigned it and when.

**Visual Reference:** Figure {{ref:incoming-review-assign}}.

**Important Notes:** To change the focal person later, use **Reassign this document** and click **Reassign and notify**; the reassignment is recorded as such.

{{figure:incoming-review-assign}}

### Procedure 10.5.3: Acknowledge an assigned document

**Purpose:** Confirm, as focal person, that you have received the assignment.

**Who can do this:** The assigned focal person.

**Steps:**

1. Open the notification, or choose **View: Assigned to me** on the Incoming register, and open the document.
2. Read the **Assignment** panel and the Chief's instructions.
3. Click **Acknowledge receipt**.

**Expected Result:** The status becomes **Acknowledged** and the document continues in **Outgoing Monitoring** under its LGMED code, where you report your action (Section 10.6). The incoming record shows **Open in Outgoing Monitoring**.

**Visual Reference:** Figure {{ref:incoming-acknowledge}}.

{{figure:incoming-acknowledge}}

### Procedure 10.5.4: Monitor the caseload (Division Chief)

**Purpose:** See what is waiting, overdue or silent.

**Who can do this:** Administrators.

**Steps:**

1. On **Incoming Monitoring**, click **Monitoring dashboard**.
2. Review the figures, **Incoming Documents for Review**, **Overdue Documents**, **Awaiting a Focal Person Update**, **Latest Updates** and **Documents by Focal Person**.
3. Click any figure to open the documents it counts.

**Expected Result:** The register opens filtered to those documents.

**Important Notes:** *Awaiting a focal person update* means assigned, not finished, and nothing reported for 7 days.

{{figure:incoming-dashboard}}

### Procedure 10.5.5: Produce a monitoring report

**Purpose:** Print or export one of the ten monitoring reports.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. On **Incoming Monitoring**, click **Monitoring reports**.
2. Under **Reports**, click a report: Incoming Documents Report; Documents for Division Chief Review; Documents by Focal Person; Documents by Status; Pending Documents Report; Overdue Documents Report; Completed Documents Report; Response / Action Monitoring Report; Processing Time Report; Assignment Monitoring Report.
3. Under **Filters**, set the text search, **Received from** / **Received to**, **Focal person**, **Status**, **Document type** and **Sort by**, then click **Apply** (or **Clear**).
4. Click **Print**, or **Export CSV** to download the same rows.

**Expected Result:** The report shows the filtered documents; the CSV contains exactly the same rows. Exports are recorded in the audit log.

{{figure:incoming-reports}}

### D. Workflow

{{diagram:incoming}}

## 10.6 Outgoing Monitoring

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Outgoing Monitoring** (`/app/outgoing/`) |
| Purpose | Follow the action on documents the focal person has acknowledged: progress updates, returns for revision, and the communication finally sent. Historical outgoing records can be imported from the spreadsheet register. |
| Who | All roles can view. The focal person reports updates and records the communication sent; Administrators can also return a document to the focal person. |
| Views | All, Assigned to me, For action (open), Action completed, Communication not yet sent, From the spreadsheet register. |

### B. Visual interface guide

{{figure:outgoing-list}}

{{figure:outgoing-update}}

### C. Procedures

### Procedure 10.6.1: Report action taken (record an update)

**Purpose:** Tell the Division what you did and where the document now stands.

**Who can do this:** The assigned focal person, once the assignment is acknowledged. The Division Chief (Administrators) may also record an update, for example to close a record.

**Steps:**

1. Open the outgoing record (**View: Assigned to me**).
2. Under **Action and Updates › Provide an update**, describe the **Action taken\*** and add **Remarks** if needed.
3. Choose the **Current status\***: In progress, For action, Pending or Completed.
4. Optionally attach a **Supporting attachment**.
5. Click **Record update**.

**Expected Result:** The update is listed on the record, the status changes to the one you chose, and the **Action Progress** panel moves on. Choosing **Completed** stamps the completion time.

**Important Notes:** The update and the status change are one act, so the record always reflects the latest report.

### Procedure 10.6.2: Return a document for revision

**Purpose:** Send the work back to the focal person with instructions.

**Who can do this:** Administrators.

**Steps:**

1. Open the outgoing record.
2. Under **Return for revision**, explain **What needs revision\***.
3. Click **Return to focal person**.

**Expected Result:** The status becomes **Returned / for revision** and the focal person is notified.

{{figure:outgoing-return}}

### Procedure 10.6.3: Record the communication sent

**Purpose:** Record the reply or transmittal that closed the matter.

**Who can do this:** The focal person and Administrators.

**Steps:**

1. Open the outgoing record and click **Record communication sent**.
2. Under **Communication**, enter the **Date sent\***, **Type of communication** and **Subject / title\***.
3. Under **Transmittal**, enter **Sent to**, **Sent via** and the **DMS number (outgoing)**, plus any **Remarks**.
4. Under **File**, attach the **File of the communication** (for example, the signed and scanned reply).
5. Click **Save communication details**.

**Expected Result:** The record's **Communication Sent** panel shows the details. The file is also filed in the Document Management register with the incoming document.

> **IMPORTANT:** Recording the communication sent does **not** close the document. The focal person must still record an update with the status **Completed** (Procedure 10.6.1).

**Important Notes:** Accepted files: PDF, Word, Excel, PowerPoint or an image (JPG, PNG, TIFF), up to 25 MB.

{{figure:outgoing-sent}}

## 10.7 Data Sync (spreadsheet import)

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Data Sync** (`/app/sync/`); also **Sync from Excel** on Outgoing Monitoring |
| Purpose | Bring the Incoming and Outgoing Excel registers into the system. |
| Who | **Outgoing** import: Encoder, LGMED Staff, Administrators. **Incoming** sync: Administrators. Viewers have no access. |
| Two types | **Incoming** — *keep in step with the register*: new rows are added and changed rows updated; the **Docket Number** is the key, and a blank cell never erases a stored value. **Outgoing** — *import historical records once*: existing records are never changed; the **LGMED Code** is the key. |

### B. Visual interface guide

{{figure:sync-home}}

{{figure:sync-preview}}

### C. Procedures

### Procedure 10.7.1: Sync a register from Excel

**Purpose:** Import or update records from the spreadsheet register.

**Who can do this:** See the table above.

**Steps:**

1. Click **Data Sync** in the sidebar.
2. Under **Select migration type**, click **Incoming** or **Outgoing**.
3. Check **Columns read** to confirm your workbook uses recognised column headings (for Incoming: Date, HUC/Province, Docket Number, Subject, Assigned Focal/Remarks; for Outgoing: LGMED Code, DNS Number (Incoming), Type of Communication / Documents, Subject / Title, Sent To, Sent Via, Remarks, DNS Number (Outgoing)).
4. Choose the file in **Excel workbook\*** and click **Upload and preview**.
5. Read the preview: **Will be created**, **Will be updated**, **Already up to date**, **Skipped** and **Kept, with a note**. Under **Sheets**, untick any sheet you do not want and click **Redraw preview for the ticked sheets**.
6. Click **Commit sync** to save, or **Discard** to throw the upload away.

**Expected Result:** After **Commit sync**, the records appear in Incoming or Outgoing Monitoring. The upload is listed under **Recent uploads**.

**Important Notes:**

- **Nothing is saved until you click Commit sync.** The preview is safe to inspect.
- For Outgoing, the result page offers **Import Valid Records** and an **Import Error Report** listing the rows that could not be imported.
- Records imported for Incoming carry the status *Imported from spreadsheet*.

> **NOTE:** Figure {{ref:sync-preview}} was produced by uploading a small illustrative workbook created for this manual (three sample rows), not a real office register.
