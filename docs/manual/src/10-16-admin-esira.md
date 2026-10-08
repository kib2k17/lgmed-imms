## 10.16 Public Website

### A. Module overview

| Item | Details |
|---|---|
| Where | **Sidebar › Public Website** (`/app/settings/public-site/`) |
| Purpose | One page that shows **what the public can see right now** (counted from the records), links to manage each kind of public content, and holds the website's **standing text**: homepage heading and introduction, mandate, About the Division, core functions, office details, privacy notice and accessibility statement. |
| Who | LGMED Staff and Administrators. |

{{figure:publicsite-admin}}

**What makes content public.** Nothing is public until someone decides it should be:

| Content | Becomes public when |
|---|---|
| Announcements | **Published on the public website** is ticked and the publication date has arrived. |
| Programs, projects, activities | An Administrator publishes the approved record (Section 10.3). Files also need a publication authority. |
| Frontline services | **Published on the public website** is ticked. |
| Documents | The document is **Completed** and, on its edit form, **Available on the public website** is ticked (the box is not offered when a document is first registered). Archiving takes it off the site. |
| Reports | The report's status is **Published**. |
| Calendar | The activity is **Organization-wide** and **Show on the public calendar** is ticked. |
| Accomplishments | The week is published and inside the disclosure window; only cleared items are listed. |

### Procedure 10.16.1: Update the website's standing text

**Who can do this:** LGMED Staff, Administrators.

**Steps:**

1. Click **Public Website** in the sidebar.
2. Under **Website text**, edit the **Homepage**, **About the Division**, **Office details** and **Standing notices** fields. Fields marked \* are required.
3. Click **Save website text**.
4. Use **Public pages** (each opens in a new tab) to check the result.

**Expected Result:** The homepage, About page and footer show the new text immediately.

{{figure:publicsite-home}}

> **NOTE:** The administrator can take the whole public website offline for maintenance with **System Settings › Public website available** (Section 10.17). Visitors then see a maintenance notice; staff sign-in is unaffected.

## 10.17 Administration

The **Administration** group in the sidebar is shown to Administrators and the System Administrator only.

### A. Module overview

| Page | Where | Purpose | Who |
|---|---|---|---|
| **Users & Roles** | `/accounts/users/` | Create, edit, deactivate and reactivate accounts; reset passwords and two-step verification; open the permission matrix. | Administrators |
| **Roles & Permissions** | `/accounts/roles/` | The permission matrix, generated from the rules the system enforces. | Administrators |
| **Menu Permissions** | `/accounts/menu-permissions/` | Close modules to a whole role or to one account. | System Administrator only |
| **System Settings** | `/app/settings/` | Preferences and reference lists. | Administrators |
| **Audit Logs** | `/app/audit-logs/` | The append-only record of every change, sign-in, export and refused access. | Administrators |

### B. Visual interface guide

{{figure:users-list}}

{{figure:users-detail}}

### C. Procedures

### Procedure 10.17.1: Create a user account

**Who can do this:** Administrators.

**Steps:**

1. Click **Users & Roles › Add Account**.
2. Under **Account**, enter the **Username\***, **First name**, **Last name** and **Email address\***.
3. Under **Designation**, enter the **Position**, **Office**, **Contact number** and **Initials for LGMED codes** (used in LGMED control codes; include the middle initial if the office's naming rule requires it).
4. Under **Access**, choose the **Role\*** and keep **Active** ticked.
5. Click **Save**.

**Expected Result:** The account is created and listed. Where e-mail is configured, the system sends the new user an account notice.

**Visual Reference:** Figure {{ref:users-new}}.

**Important Notes:** Give each person the **lowest role** that lets them do their work. Administrator accounts must set up two-step verification at their first sign-in.

{{figure:users-new}}

### Procedure 10.17.2: Reset a user's password

**Steps:** Open the user, click **Reset password**, enter and confirm the new password, and click **Set new password**. Give the password to the user privately and ask them to keep it secret. Weak or mismatched passwords are refused.

### Procedure 10.17.3: Edit an account or change a role

**Steps:** Open the user, click **Edit**, change the details or **Role**, and click **Save**. Role changes are recorded in the audit log.

**Important Notes:** You cannot change **your own** role or deactivate **your own** account.

### Procedure 10.17.4: Deactivate an account or reset two-step verification

**Steps:**

1. Open the user.
2. Click **Deactivate** and confirm with **Deactivate account**. The person can no longer sign in. Reactivate it later with **Reactivate** on the same page.
3. If the person lost their phone and recovery codes, click **Reset two-step verification** in the **Two-Step Verification** panel; they will set it up again at their next sign-in.

**Important Notes:** Accounts are **never deleted**, so everything a person did remains attributable to them.

{{figure:users-roles}}

### Procedure 10.17.5: Close modules to a role or an account (Menu Permissions)

**Who can do this:** System Administrator only.

**Steps:**

1. Click **Menu Permissions** in the sidebar (or **Menu permissions** on a user's page).
2. Under **Modules by Role**, untick a module for a role to close it (or tick to reopen it), then click **Save role permissions**.
3. Under **Modules by Account**, choose an account and click **Set modules** to set modules for that person only.

**Expected Result:** Closed modules disappear from the affected users' sidebars, and their addresses are refused.

**Important Notes:** Menu Permissions can only **narrow** access. A module a role is not permitted to use by its role cannot be opened to it here.

{{figure:users-menu-permissions}}

### Procedure 10.17.6: Change system settings and reference lists

**Who can do this:** Administrators.

**Steps:**

1. Click **System Settings**.
2. Under **Preferences**, set:
    - **Records per page\*** (5–100) — rows in every list;
    - **Session warning\*** (1–60 minutes) — how long before the session expires the warning appears;
    - **System notice** and **Notice level\*** (Information, Warning, Urgent) — a banner shown to every signed-in user; tick **Cover the page and sound an alert** for an urgent full-screen notice; leave the notice empty for no banner;
    - **Public website available** — untick to show a maintenance notice on the public website.
3. Click **Save settings**.
4. To maintain a reference list (**Program categories**, **Document types** with their retention periods, **Departments, divisions and sections**, **Disposal authorities**, **Provinces**), click **Add**, or **Edit** / **Remove** on a row.

**Expected Result:** Settings take effect immediately for all users.

**Important Notes:** An entry that is in use cannot be removed; the system explains why. The **System Information** panel shows the version; **Administration** links to Users & roles, the permission matrix, the audit logs and the Django administration site (technical use only).

{{figure:settings-page}}

### Procedure 10.17.7: Search the audit log

**Who can do this:** Administrators.

**Steps:**

1. Click **Audit Logs**.
2. Enter a **From date** and **To date** and click **Apply dates**, and/or tick **Only entries needing attention** (failed sign-ins, refused access and similar).
3. Search by actor, record or detail; filter by **Action**, **Record type** and **Actor**; click **Apply**.
4. Click an entry to see its details, including field-by-field changes.
5. Click **Export CSV** to download the filtered entries.

**Expected Result:** The matching entries are listed, newest first.

**Important Notes:** The audit log cannot be edited or deleted from the system. Passwords are never recorded.

{{figure:audit-list}}

## 10.18 e-SIRA — Electronic Signature, Identification, Routing and Approval

### A. Module overview

| Item | Details |
|---|---|
| Where | **LGMED Innovation Action › e-SIRA**, pinned at the foot of the sidebar (`/app/esira/`). Tabs: **Dashboard**, **Documents**, **My Digital Certificate**, **My Signature Style**, and for administrators **Certificate Verification** and **Audit Trail**. |
| Purpose | Upload or scan a document, place signature boxes, route it to signers and approvers in order, sign it digitally with a DICT PNPKI certificate, track it, and download the signed PDF. |
| Who | **Open e-SIRA and act on documents routed to you**: every active account (Viewers included). **Upload, place boxes, route**: Encoder, LGMED Staff, Administrators. **See all documents, cancel**: Administrators. **Verify certificates**: Administrators. |
| Step actions | Signature; Approval; Review / initials; For information / acknowledgement. |
| Statuses | Draft, Awaiting Signature, Out for Signature, Partially Signed, Routed, Fully Signed, Routing Completed, Completed, Rejected, Cancelled. |

> **IMPORTANT:** A **signature box** only marks *where* a signature will go and *whose* it is; it proves nothing. A **digital signature** is a real cryptographic signature made with the signer's own DICT PNPKI certificate. There is no simulated signing: a document is marked signed only after a real signature is found in the file.

### B. Visual interface guide

{{figure:esira-dashboard}}

### C. Procedures

### Procedure 10.18.1: Register your digital certificate (one time)

**Purpose:** Prepare to sign documents.

**Who can do this:** Anyone who will sign.

**Steps:**

1. Open **e-SIRA › My Digital Certificate** (or **My certificates**).
2. Under **Digital certificate**, choose your PNPKI **.p12** file and type the **Certificate password\***.
3. Optionally upload a **Signature image** (PNG or JPG) to be drawn inside your signature boxes.
4. Keep **Require .p12 password when signing** switched on (recommended).
5. Click **Save certificate**.
6. Ask an administrator to verify the certificate (Procedure 10.18.6).

**Expected Result:** The certificate appears under **My Registered Certificates** as awaiting verification. You can sign once it is verified.

**Important Notes:** The file and password are stored encrypted. Until your certificate is verified you can still approve, review and acknowledge documents, but not sign.

{{figure:esira-certificate}}

{{figure:esira-styles}}

### Procedure 10.18.2: Upload a document and prepare signature boxes

**Who can do this:** Encoder, LGMED Staff, Administrators.

**Steps:**

1. Click **Upload / Scan Document**.
2. Enter the **Title\***, and optionally the **Document type** and **Description**.
3. Under **How is the document coming in?**, choose **Upload a PDF** and select the **PDF file**, or choose **Scan pages** and select the scanned images (they are combined into a PDF).
4. Click **Upload and prepare**. The signing workspace opens.
5. In **Signature Boxes**, choose the **Signer for new boxes**, click **Add Signature Box**, and drag the box into place. Use **Apply to All Pages** if needed; **Remove All Boxes** clears them.

**Expected Result:** The document is saved as a **Draft** with its boxes. Version 1 (the original) is never changed.

**Visual Reference:** Figures {{ref:esira-upload}} and {{ref:esira-workspace}}.

**Important Notes:** Upload limit 25 MB.

{{figure:esira-upload}}

{{figure:esira-workspace}}

### Procedure 10.18.3: Route the document

**Steps:**

1. In the workspace, click **Route for signature**.
2. For each step, choose the **Recipient**, the **Action required** (Signature, Approval, Review / initials, For information / acknowledgement), the **Purpose / instructions** and an optional due date.
3. Click **Add a step** for more recipients; steps run in order. **Remove this step** deletes one.
4. Click **Send on route**.

**Expected Result:** The first recipient is notified and the document's status changes (for example **Out for Signature** or **Routed**).

**Visual Reference:** Figures {{ref:esira-route}} and {{ref:esira-route-filled}}.

{{figure:esira-route}}

{{figure:esira-route-filled}}

### Procedure 10.18.4: Act on a document routed to you

**Who can do this:** The recipient whose turn it is.

**Steps:**

1. Open the document from **Waiting on Me** on the e-SIRA dashboard, or from your notification.
2. Click **View document** to read it.
3. Optionally type **Remarks** (required when rejecting; recorded on the routing slip). To pass it on after you, open **Forward to someone else after me** and choose the person, their action and instructions.
4. Depending on the step, click **Approve**, **Mark reviewed** or **Acknowledge**; or **Reject and return** to stop the route and send it back to the owner.
5. For a signature step, click **Open to sign** and follow Procedure 10.18.5.

**Expected Result:** Your step is recorded in **Routing History** and the next recipient is notified.

{{figure:esira-act}}

### Procedure 10.18.5: Sign a document

**Who can do this:** The recipient of a signature step, with a **verified** PNPKI certificate.

**Steps:**

1. Open the document and click **Open to sign**.
2. Click **Sign Document** (or **Apply digital signature**).
3. In the sign dialog, type your certificate password (if required), choose a **Signature style**, optionally enter a **Reason for signing** and **Remarks**, and confirm.

**Expected Result:** A digital signature is applied in each of your boxes as a new version of the PDF; earlier signatures stay valid.

**Important Notes:** Signing is refused unless the certificate is registered to you, verified by an administrator, in date, and issued under the DICT PNPKI roots installed on the server. Refused attempts are recorded.

> **NOTE:** The signing dialog and a signed result were **not captured** for this manual, because the documentation copy has no PNPKI certificate. See the documentation report for the screenshots still required.

### Procedure 10.18.6: Verify a registered certificate (administrators)

**Steps:**

1. Open **e-SIRA › Certificate Verification**.
2. Under **Awaiting Verification**, compare the certificate's name, e-mail and serial number with the DICT PNPKI issuance record for that employee.
3. Click **Verify**, or **Reject**. A verified certificate can later be withdrawn with **Revoke**.

**Important Notes:** An administrator cannot verify their own certificate.

{{figure:esira-verification}}

### Procedure 10.18.7: Track, complete and download

**Steps:**

1. Open **e-SIRA › Documents** and use the views (**Awaiting my signature**, **Waiting on me**, **Owned by me**, **Out for signature**, **Signed by me** …) or the **Status** filter.
2. Open a document to see **Status**, **Routing History**, **Digital Signatures**, **Versions** and **Audit Trail**.
3. Click **Verify signatures** to check the signatures in the file itself.
4. When every step is done, the owner clicks **Mark as completed**; the document is locked.
5. Click **Download signed PDF** (or **Download version N**).

**Important Notes:** The owner or an administrator can **Cancel document** with a reason. Every view, download, box change, routing step and signature is recorded in the e-SIRA **Audit Trail**.

{{figure:esira-documents}}

### D. Workflow

{{diagram:esira}}
