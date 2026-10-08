# 10. Module-by-Module Instructions

This chapter takes each module in the order it appears in the sidebar. Every module section has the same parts:

- **A. Module overview** — purpose, who may use it, and what it can do;
- **B. Visual interface guide** — annotated screenshots with numbered markers and a legend;
- **C. Step-by-step procedures** — one procedure per task;
- **D. Workflow** — for modules where a record passes between people.

My Profile and Notifications, reached from the top bar, come first because every user needs them.

## 10.1 My Profile and Two-Step Verification

### A. Module overview

| Item | Details |
|---|---|
| Where | Account menu › **My profile** (`/accounts/profile/`) |
| Purpose | See your account details, role and permissions; upload a profile photo; set up two-step verification; see your recent activity. |
| Who | All roles. |
| Actions | Upload or remove a profile photo; request a correction; set up, renew recovery codes for, or switch off two-step verification. |

### B. Visual interface guide

{{figure:profile-page}}

### C. Procedures

### Procedure 10.1.1: Upload a profile photo

**Purpose:** Show your photo beside your name in the system.

**Who can do this:** All roles.

**Steps:**

1. Open the **Account menu** and click **My profile**.
2. In **Account Details**, under **Profile photo**, click the file field and choose a picture.
3. Click **Upload** (marker 2).

**Expected Result:** The photo replaces your initials in the top bar and on your account.

**Important Notes:** JPEG, PNG or WebP, up to 5 MB. The picture is cropped to a square.

### Procedure 10.1.2: Request a correction to your account details

**Purpose:** Have the administrator correct your name, position, office or e-mail.

**Steps:**

1. On **My Profile**, click **Request a correction** (marker 3).
2. Your e-mail program opens a message to the office. Describe the correction and send it.

**Expected Result:** An administrator updates your account (Procedure 10.17.3).

**Important Notes:** You cannot change your own role or account details yourself.

{{figure:profile-mfa-setup}}

### Procedure 10.1.3: Set up two-step verification

**Purpose:** Protect your account with a code from your phone in addition to your password.

**Who can do this:** All roles. **Mandatory for Administrators and System Administrators.**

**Steps:**

1. Install an authenticator app on your phone (for example Google Authenticator or Microsoft Authenticator).
2. On **My Profile**, click **Set up two-step verification** (marker 5).
3. Under **Connect your authenticator app**, follow the steps on the page: in the app, add an account and scan the QR code. If you cannot scan it, choose *enter a setup key* in the app and type the key shown.
4. Type the six-digit code the app now shows into the **Authentication code** field and click **Turn on two-step verification**.
5. The system shows your **recovery codes**. Print them or write them down and keep them somewhere safe.

**Expected Result:** **Two-Step Verification** on your profile shows that it is on. From the next sign-in, you will be asked for a code after your password.

**Important Notes:**

- Each recovery code can be used once, if your phone is lost. You can generate a new set from **My Profile**; the old set then stops working.
- If you lose both your phone and your recovery codes, an administrator can reset two-step verification on your account (Procedure 10.17.4).
- The new phone replaces the old one only after it has produced a correct code, so a half-finished setup never locks you out.

## 10.2 Notifications

### A. Module overview

| Item | Details |
|---|---|
| Where | The bell in the top bar, and **View all** in its drop-down (`/app/notifications/`) |
| Purpose | Tell you about work that is waiting on you: items to review, documents assigned to you, overdue work, items awaiting publication, account and system notices. |
| Who | All roles. Notifications are addressed to a person, never to a whole role. |
| Actions | Open, dismiss, mark all as read, filter by category and priority, show unread only. |

### B. Visual interface guide

{{figure:notifications-list}}

### C. Procedures

### Procedure 10.2.1: Open and clear notifications

**Purpose:** Go to the record a notification concerns, and keep the list tidy.

**Who can do this:** All roles.

**Steps:**

1. Click the bell in the top bar. The latest notifications are listed (Figure {{ref:ui-notification-bell}}).
2. Click a notification to open the record it concerns, or click **View all** to open the Notifications page.
3. On the Notifications page, use **Category** (marker 3) and **Priority** (marker 4) and click **Apply** to narrow the list, or click **Unread only** (marker 2).
4. Click **Open** on a notification to go to its record, or **Dismiss** to remove it from your list.
5. Click **Mark all read** (marker 1) to clear the unread count.

**Expected Result:** Opened notifications are marked as read and the bell's count goes down.

**Important Notes:** A notification **withdraws itself when the work is done** — for example, once a report is approved it stops asking to be reviewed. A standing problem (such as a follow-up that is three weeks overdue) produces **one** notification, not one per day. See Chapter 12.

## 10.3 Programs, Projects and Activities (PPAs)

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Programs & Projects** (`/app/programs/`); **PPA Review Queue** (`/app/programs/queue/`); **Publication Authorities** (`/app/programs/authorities/`) |
| Purpose | Record the Division's Programs, Projects, Sub-projects and Activities under the Department's five Organizational Outcomes; attach supporting documents and photographs; review them; and publish cleared content to the public website. |
| Who | **Encode** (create, edit, upload, submit): Encoder, LGMED Staff, Administrators. **Review** (decide on content and files; record memoranda): LGMED Staff, Administrators. **Publish** (publish, take down, archive): Administrators. **Delete**: Administrators. Viewers read only. |
| Organisation | Five Organizational Outcomes › Programs › Projects › Sub-projects › Activities. An activity belongs to a project or to a sub-project. |

The five Organizational Outcomes are: *Excellence in Local Governance Upheld*; *Peaceful, Orderly, Safe, and Secure Communities Strengthened*; *Resilient Communities Reinforced*; *Inclusive Communities Enabled*; *Highly Trusted Department and Partner*.

**Publication statuses**

| Status | Meaning |
|---|---|
| Draft | Being written. |
| For review | Submitted to a reviewer. |
| Screening | Attached files are being scanned (brief). |
| Review required | The screening flagged something, or could not read a file. |
| Approved | A reviewer read it and cleared the content. |
| Published | Live on the public website. |
| Unpublished | Taken off the public website. |
| Archived | Closed out; kept for the record; not public. |

### B. Visual interface guide

{{figure:programs-workbench}}

{{figure:programs-detail}}

{{figure:programs-publication}}

### C. Procedures

### Procedure 10.3.1: Add a program

**Purpose:** Create a new programme record.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Click **Programs & Projects** in the sidebar.
2. Click **Add Program** (Figure {{ref:programs-workbench}}, marker 5).
3. Fill in **Program information**: **Title\***, **Organizational outcome\***, and optionally Reference number, Category, Description and Objectives.
4. Fill in **Implementation period** (Start date, End date, **Implementation status\***).
5. Fill in **Responsibility and coverage**: Responsible office / division, Lead office, Focal person and **Covered LGUs** (hold **Ctrl** to select several).
6. Optionally change the **Public page headings**.
7. Click **Save**.

**Expected Result:** The program record opens with the status **Draft**.

**Visual Reference:** Figure {{ref:programs-new}}.

{{figure:programs-new}}

### Procedure 10.3.2: Add a project, sub-project or activity

**Purpose:** Build the tree under a programme.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Open the parent record (click its title on the workbench).
2. In the **Projects**, **Sub-Projects** or **Activities** panel, click **Add**. (On the workbench, the **Project**, **Add a sub-project** and **Add an activity** links do the same.)
3. Complete the form and click **Save**.

**Expected Result:** The new record opens and is listed under its parent.

### Procedure 10.3.3: Upload supporting documents or photographs

**Purpose:** Attach the papers and photographs behind a record. Each file is automatically screened for personal or confidential information.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Open the record and click **Upload document** (Figure {{ref:programs-detail}}, marker 3).
2. In **File or photographs\***, choose one file, or several photographs at once.
3. Enter the **Document title\*** and choose the **Type of document\***.
4. Optionally add a **Description**.
5. Tick **I have opened these files and checked what is in them\***.
6. Click **Upload and screen**.

**Expected Result:** The file appears under **Supporting documents** with its screening result.

**Visual Reference:** Figure {{ref:programs-upload}}.

**Important Notes:**

- Accepted: PDF, Word, Excel, PowerPoint, JPG and PNG, up to 25 MB.
- The screening looks for things such as government ID numbers, bank details, contact numbers, signatures, attendance sheets, confidentiality markings and passwords. A clean result is **Low risk**, which means *nothing was found* — it is not an approval. A file the scanner could not read is marked **Review required**.
- Uploaded files are stored internally and are **never public** until approved, cited against a publication authority, and published.

{{figure:programs-upload}}

### Procedure 10.3.4: Submit a record for review

**Purpose:** Hand a finished record to a reviewer.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Open the record and scroll to **Publication**.
2. Click **Submit for review**.

**Expected Result:** The status becomes **For review** (or **Review required** if a file was flagged) and the record appears in the **PPA Review Queue**.

### Procedure 10.3.5: Review a record (approve, request revision, or reject)

**Purpose:** Clear content for publication, or send it back.

**Who can do this:** LGMED Staff, Administrators.

**Steps:**

1. Click **PPA Review Queue** in the sidebar (Figure {{ref:programs-queue}}).
2. Under **Content awaiting review**, click **Review** beside the record.
3. Read the record and open each supporting file. Files with findings are listed under **Files awaiting review**; open each, read **What the screening found**, and record a decision on the file.
4. In **Your decision**, choose **Approve the content**, **Request revision** or **Reject**.
5. Enter **Review comments** — required when requesting revision or rejecting.
6. Click **Record decision**.

**Expected Result:** Approved records move to **Approved** and wait for an administrator to publish. Records sent back return to the encoder with your comments.

**Visual Reference:** Figure {{ref:programs-decision}}.

**Important Notes:** On a file, the choices are **Approve for publication**, **Request revision** and **Reject**. A **High risk** file can be approved only after ticking *I have opened and read this file in full, and I confirm it contains nothing that should not be released.*

{{figure:programs-queue}}

{{figure:programs-decision}}

### Procedure 10.3.6: Record a publication authority (memorandum)

**Purpose:** Record the memorandum that authorises releasing files to the public. A file can be published only when it is cited against an authority that is in effect.

**Who can do this:** LGMED Staff, Administrators.

**Steps:**

1. Click **Publication Authorities** in the sidebar.
2. Click **Record a memorandum**.
3. Complete **The issuance** (reference, title, date approved, approved by), **What it covers** (scope, and the signed memorandum file) and **Period of effect** (effective from, effective until, and whether it is active), then click **Save**. The memorandum file is stored internally and is never itself published.
4. When reviewing a file, choose this memorandum in **Published under** / **Memorandum**.

**Expected Result:** The memorandum is listed with the number of files released under it.

**Visual Reference:** Figure {{ref:programs-authorities}}.

**Important Notes:** Withdrawing a memorandum stops it authorising anything further; it does not unpublish files it already released.

{{figure:programs-authorities}}

### Procedure 10.3.7: Publish, take down, archive or restore a record

**Purpose:** Put approved content on the public website, or remove it.

**Who can do this:** Administrators.

**Steps:**

1. Open the record. Optionally click **Preview public page** to check how it will look.
2. In **Publication**, click **Publish to the public website** (marker 3 of Figure {{ref:programs-publication}}).
3. To remove it later, click **Take off the public website**. To close it out, click **Archive**; an archived record can be brought back with **Restore from the archive**.

**Expected Result:** A published record appears on the public website under **Programs**. Approved files that are cited against an authority are released with it; files without an authority are held back and named on the page.

**Important Notes:** A record is visible to the public only while every level above it is also published.

### Procedure 10.3.8: Arrange photographs

**Purpose:** Choose the order in which a record's photographs appear on its public page.

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Open the record. When it has photographs, **Supporting documents** shows a link **Arrange N photographs**.
2. Click it, put the photographs in the order you want, and save.

**Expected Result:** The public page shows the photographs in the new order.

> **NOTE:** No screenshot is included: the demonstration data has no photographs, so the link does not appear. See the documentation report.

### Procedure 10.3.9: Delete a record

**Who can do this:** Administrators.

**Steps:** Open the record, scroll to **Delete**, click **Delete this program** (or project/activity), and confirm.

**Important Notes:** **WARNING:** Deletion cannot be undone. Prefer **Archive** for records that should be kept.

### D. Workflow

{{diagram:ppa}}
