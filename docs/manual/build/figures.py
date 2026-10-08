"""
Every screenshot in the user manual, described once.

Each entry says who is signed in, which page is opened, what is done before
the picture is taken, and which controls are marked. `markers` are
(selector, label, explanation); their order is the number drawn on the image
and the row in the legend printed beneath it in the manual.

Selectors are Playwright selectors, plus two shorthands understood by
capture.py:
    card:<Heading text>   the panel that carries that heading
    field:<Label text>    a form field together with its label

The manual refers to a figure as {{figure:<id>}}; build.py replaces the token
with the image, its numbered caption and its legend.
"""

import os
from pathlib import Path

BASE_URL = os.environ.get("LGDOCS_URL", "http://127.0.0.1:8765")
DEMO_PASSWORD = "LgmedDemo!2026"   # bootstrap_demo's development-only password
SAMPLES = Path(os.environ.get("LGDOCS_WORKDIR", r"C:\lgdt")) / "samples"

SA, AD, ST, EN, VW = ("lgmed.superadmin", "lgmed.admin", "lgmed.staff",
                      "lgmed.encoder", "lgmed.viewer")
ROLE_LABELS = {
    SA: "System Administrator", AD: "Administrator (Division Chief)",
    ST: "LGMED Staff", EN: "Encoder", VW: "Viewer", None: "Public visitor",
}

SIDEBAR = "#sidebar"


def nav(label):
    return f'{SIDEBAR} >> role=link[name="{label}"]'


def link(name):
    return f'main >> role=link[name="{name}"]'


def button(name):
    return f'main >> role=button[name="{name}"]'


EXPORT = (link("Export CSV"), "Export CSV",
          "Downloads the rows currently listed - with the search and filters applied - as a spreadsheet file. Every export is recorded in the audit trail.")
SEARCH = ("#table-search", "Search box", "Type part of a name, title, code or other text, then press Enter or click Apply.")
APPLY = (button("Apply"), "Apply", "Runs the search and filters.")
TABLE = ("main table", "Records table", "One row per record. Underlined column headings sort the list; click again to reverse the order.")
FIRST_ROW_VIEW = ("main tbody tr >> nth=0 >> role=link[name=/^(View|Open)/]", "Row actions",
                  "View (eye), Edit (pencil) and Delete (bin) for that record. Only the actions your role permits are shown.")
PAGER = ('nav[aria-label^="Pagination"]', "Pagination", "Moves between pages of results. The number of rows per page is a system setting.")


FIGURES = [
    # ------------------------------------------------------------------ access
    {"id": "access-login", "module": "access", "user": None, "url": "/accounts/login/",
     "caption": "The staff sign-in page (/staff or /accounts/login/)",
     "markers": [
         ("field:Username", "Username", "The username issued by the system administrator."),
         ("field:Password", "Password", "Your password. The eye button shows or hides what you typed; a warning appears if Caps Lock is on."),
         ('role=link[name="Forgot password?"]', "Forgot password?", "Opens an e-mail to the office asking for a password reset. Passwords are reset by an administrator."),
         ('role=button[name="Sign in"]', "Sign in", "Submits your username and password."),
     ]},
    {"id": "access-privacy", "module": "access", "user": VW, "accept_privacy": False, "url": "/app/",
     "caption": "The Data Privacy Notice shown at first sign-in",
     "markers": [
         ("dialog[open] h2", "Notice title", "Data Privacy Act of 2012 (Republic Act No. 10173). Scroll to read all sections."),
         ("dialog[open] input[type=checkbox]", "Agreement box", "Tick to confirm you have read and agree to the notice."),
         ('dialog[open] >> role=button[name="Decline and sign out"]', "Decline and sign out", "Leaves the system without accepting. You cannot use LGMED-iMMS until you accept."),
         ('dialog[open] >> role=button[name="I Agree and Continue"]', "I Agree and Continue", "Becomes available once the box is ticked; records your acceptance and opens the system."),
     ]},
    {"id": "access-account-menu", "module": "access", "user": AD, "url": "/app/",
     "ops": [("click", 'button:has-text("Account menu")')],
     "crop": (840, 0, 600, 430),
     "caption": "The account menu in the top bar",
     "markers": [
         ('button:has-text("Account menu")', "Account menu", "Your name and position. Click to open or close the menu."),
         ('[data-menu-panel] >> role=link[name="My profile"]', "My profile", "Your account details, profile photo, permissions and two-step verification."),
         ('[data-menu-panel] >> role=link[name="Public website"]', "Public website", "Opens the public LGMED website."),
         ('[data-menu-panel] >> role=button[name="Sign out"]', "Sign out", "Ends your session. Always sign out on a shared computer."),
     ],
     "after": [("press", "Escape")]},

    # --------------------------------------------------------------- interface
    {"id": "ui-layout", "module": "interface", "user": AD, "url": "/app/",
     "caption": "Parts of the LGMED-iMMS screen (Dashboard, signed in as the Division Chief)",
     "markers": [
         ("text=Secure internal system", "System banner", "Confirms you are in the secure internal system, for authorised personnel only."),
         ("#global-search", "Search records", "Quick search box in the top bar."),
         ('header [data-menu]:has([data-notif-badge]) >> [data-menu-button]', "Notifications bell", "The red badge counts your unread notifications. Click to see the latest."),
         ('button:has-text("Account menu")', "Account menu", "Profile, public website and Sign out."),
         ('ul[aria-labelledby="nav-section-1"]', "Sidebar - Main", "Operational modules. You only see the modules your role and menu permissions allow."),
         (nav("Dashboard"), "Current page", "The highlighted item shows where you are."),
         ('#sidebar >> role=link[name*="e-SIRA"]', "LGMED Innovation Action", "e-SIRA, pinned at the foot of the sidebar."),
         ('nav[aria-label="Breadcrumb"]', "Breadcrumb", "The path to the current page. Click an earlier part to go back."),
         ("main h1", "Page title", "The name of the page, with a short description beneath it."),
         (link("New monitoring record"), "Page actions", "The main actions for the page, at the top right."),
     ]},
    {"id": "ui-notification-bell", "module": "interface", "user": AD, "url": "/app/",
     "ops": [("click", 'header [data-menu]:has([data-notif-badge]) >> [data-menu-button]')],
     "crop": (700, 0, 740, 640),
     "caption": "The notifications drop-down",
     "markers": [],
     "after": [("press", "Escape")]},

    # --------------------------------------------------------------- dashboard
    {"id": "dashboard-overview", "module": "dashboard", "user": ST, "url": "/app/",
     "caption": "The Dashboard - summary figures",
     "markers": [
         ("card:Total Programs", "Summary figure", "A headline count taken directly from the records."),
         ('main >> role=link[name="View details for Total Programs"]', "View details", "Opens the records behind the figure."),
         (link("Export reports"), "Export reports", "Downloads the Reports register as a CSV file."),
         (link("New monitoring record"), "New monitoring record", "Shortcut to record a monitoring activity (roles that may encode)."),
         ("text=Figures as of", "Time stamp", "When the figures were calculated (Philippine Standard Time)."),
     ]},
    {"id": "dashboard-panels", "module": "dashboard", "user": ST, "url": "/app/",
     "ops": [("scroll", "card:Recent Monitoring Activities", 20)],
     "caption": "The Dashboard - recent activity and items requiring attention",
     "markers": [
         ("card:Recent Monitoring Activities", "Recent Monitoring Activities", "The latest monitoring records; click an LGU or the eye icon to open one."),
         ("card:Requires Attention", "Requires Attention", "Work waiting on the Division, such as documents awaiting review or overdue follow-ups. Each line opens the matching records."),
         ("card:Upcoming Activities", "Upcoming Activities", "Calendar activities coming up that you are allowed to see."),
     ]},

    # ----------------------------------------------------------------- profile
    {"id": "profile-page", "module": "profile", "user": ST, "url": "/accounts/profile/", "height": 1100,
     "caption": "My Profile",
     "markers": [
         ("card:Account Details", "Account Details", "Your name, username, e-mail, position and office as recorded by the administrator."),
         (button("Upload"), "Profile photo", "Choose a JPEG, PNG or WebP picture (up to 5 MB) and click Upload."),
         (link("Request a correction"), "Request a correction", "Opens an e-mail to the office to correct your account details."),
         ("card:System Access", "System Access", "Your role and the permissions it carries."),
         (link("Set up two-step verification"), "Two-step verification", "Protect your account with an authenticator app (required for administrators)."),
     ]},
    {"id": "profile-mfa-setup", "module": "profile", "user": ST, "url": "/accounts/mfa/setup/", "height": 1000,
     "caption": "Setting up two-step verification",
     "markers": []},
    {"id": "notifications-list", "module": "notifications", "user": AD, "url": "/app/notifications/",
     "caption": "The Notifications page",
     "markers": [
         (button("Mark all read"), "Mark all read", "Marks every notification as read."),
         (link("Unread only"), "Unread only", "Shows only notifications you have not opened."),
         ("#filter-category", "Category filter", "Awaiting review, Overdue, Awaiting publication, Assigned to you, Account or System."),
         ("#filter-level", "Priority filter", "Information, Needs action or Urgent."),
         ("main li >> nth=0", "Notification", "Click the title or Open to go to the record it concerns. Dismiss removes it from your list."),
     ]},

    # ---------------------------------------------------------------- programs
    {"id": "programs-workbench", "module": "programs", "user": ST, "url": "/app/programs/",
     "caption": "Programs, Projects and Activities - the workbench",
     "markers": [
         (nav("Programs & Projects"), "Programs & Projects", "Sidebar entry for the module."),
         ("main select[name=outcome]", "Organizational Outcome", "Shows the programmes under one of the Department's five outcomes, or all of them."),
         ("field:Include archived", "Include archived", "Also lists archived records."),
         (link("Review queue"), "Review queue", "Items waiting for review (reviewers only)."),
         (link("Add Program"), "Add Program", "Starts a new programme."),
         ('main >> role=link[name="Seal of Good Local Governance"]', "Programme", "Click a title to open the record."),
     ]},
    {"id": "programs-new", "module": "programs", "user": ST, "url": "/app/programs/program/new/", "height": 1500,
     "clip": "main", "pad": 0,
     "caption": "New Program form",
     "markers": [
         ("field:Title", "Title", "Required. The programme's name."),
         ("field:Organizational outcome", "Organizational outcome", "Required. Which of the five Department outcomes it serves."),
         ("field:Implementation status", "Implementation status", "Required. Pending, Active, Completed, Suspended or Archived."),
         ("field:Covered LGUs", "Covered LGUs", "Select the LGUs the programme covers."),
         ("field:Description heading", "Public page headings", "Optional headings used on the public page."),
         (button("Save"), "Save", "Saves the record as a Draft. Cancel returns without saving."),
     ]},
    {"id": "programs-detail", "module": "programs", "user": AD, "url": "/app/programs/project/1/", "height": 1000,
     "caption": "A project record (Administrator view)",
     "markers": [
         (link("Preview public page"), "Preview public page", "Shows how the page will look on the public website."),
         (link("Edit"), "Edit", "Changes the record's details."),
         (link("Upload document"), "Upload document", "Adds supporting files or photographs."),
         ("card:Sub-Projects", "Sub-Projects / Activities", "Records under this one. Add creates a new one."),
     ]},
    {"id": "programs-publication", "module": "programs", "user": AD, "url": "/app/programs/project/1/",
     "ops": [("scroll", "card:Supporting documents", 20)], "height": 1000,
     "caption": "Supporting documents and the Publication panel",
     "markers": [
         ("card:Supporting documents", "Supporting documents", "Uploaded files with their screening result and review status."),
         ("card:Publication", "Publication", "Where the record stands: Draft, For review, Screening, Review required, Approved, Published, Unpublished, Archived."),
         (button("Publish to the public website"), "Publish to the public website", "Administrators only, once the content is approved."),
         (button("Archive"), "Archive", "Closes the record out; kept, not public."),
     ]},
    {"id": "programs-upload", "module": "programs", "user": ST, "url": "/app/programs/project/1/documents/new/", "height": 1150,
     "clip": "main", "pad": 0,
     "caption": "Upload supporting documents",
     "markers": [
         ("field:File or photographs", "File or photographs", "Required. One file, or several photographs at once."),
         ("field:Document title", "Document title", "Required."),
         ("field:Type of document", "Type of document", "Issuance, report, guidelines, presentation, photograph, certificate or other."),
         ("field:I have opened these files", "Confirmation", "Required. Confirms you checked the file's contents before uploading."),
         (button("Upload and screen"), "Upload and screen", "Uploads the file and runs the automated screening for personal or confidential information."),
     ]},
    {"id": "programs-queue", "module": "programs", "user": ST, "url": "/app/programs/queue/", "height": 1150,
     "caption": "The PPA Review Queue",
     "markers": [
         (nav("PPA Review Queue"), "PPA Review Queue", "Visible to LGMED Staff, the Division Chief and administrators."),
         ("card:Files awaiting review", "Files awaiting review", "Uploaded files whose screening needs a reviewer's decision."),
         ("card:Content awaiting review", "Content awaiting review", "Records submitted for review. Click Review to open one."),
     ]},
    {"id": "programs-decision", "module": "programs", "user": ST, "url": "/app/programs/sub-project/1/",
     "ops": [("scroll", "card:Your decision", 20)],
     "clip": "card:Your decision", "pad": 14,
     "caption": "Recording a review decision on a submitted record",
     "markers": [
         ("field:Decision", "Decision", "Approve the content, Request revision, or Reject."),
         ("main textarea >> nth=-1", "Review comments", "Required when requesting revision or rejecting, so the encoder knows what to change."),
         (button("Record decision"), "Record decision", "Saves the decision; the record moves to Approved, back to Draft, or is rejected."),
     ]},
    {"id": "programs-authorities", "module": "programs", "user": AD, "url": "/app/programs/authorities/",
     "caption": "Publication Authorities",
     "markers": [
         (nav("Publication Authorities"), "Publication Authorities", "Memoranda that authorise releasing files to the public."),
         (link("Record a memorandum"), "Record a memorandum", "Records a new memorandum before any file is cited against it."),
         (TABLE[0], "Recorded memoranda", "Reference, date issued, whether it is in effect, and how many files it released."),
     ]},

    # -------------------------------------------------------------- monitoring
    {"id": "monitoring-list", "module": "monitoring", "user": AD, "url": "/app/monitoring/",
     "caption": "The Monitoring register",
     "markers": [
         (nav("Monitoring"), "Monitoring", "Sidebar entry."),
         EXPORT,
         (link("New Monitoring Record"), "New Monitoring Record", "Records a monitoring activity."),
         SEARCH,
         ("#filter-lgu__province", "Filters", "Province, LGU type, Status and Year narrow the list."),
         APPLY,
         ('main >> role=link[name^="LGU"] >> nth=0', "Sortable heading", "Click to sort by this column."),
         FIRST_ROW_VIEW,
     ]},
    {"id": "monitoring-new", "module": "monitoring", "user": EN, "url": "/app/monitoring/new/", "height": 1400,
     "clip": "main", "pad": 0,
     "caption": "New Monitoring Record form",
     "markers": [
         ("field:Activity", "Activity", "Required. What was monitored."),
         ("field:LGU", "LGU", "Required. The LGU monitored."),
         ("field:Monitoring date", "Monitoring date", "Required."),
         ("field:Monitoring team", "Monitoring team", "Required. Who conducted it."),
         ("card:Findings and Recommendations", "Findings and Recommendations", "What was found and what is recommended."),
         ("field:Follow-up due date", "Follow-up due date", "When the follow-up action falls due; overdue follow-ups raise notifications."),
         ("field:Status", "Status", "Required. Scheduled, In progress, For review, Completed or Cancelled."),
         (button("Save"), "Save", "Saves the record."),
     ]},
    {"id": "monitoring-detail", "module": "monitoring", "user": AD, "url": "/app/monitoring/1/", "height": 1100,
     "caption": "A monitoring record",
     "markers": [
         (link("Back to list"), "Back to list", "Returns to the register."),
         (button("Print"), "Print", "Prints the record."),
         (link("Edit"), "Edit", "Changes the record."),
         (button("Delete"), "Delete", "Administrators only; asks for confirmation."),
         ("card:Progress", "Progress", "Where the record stands."),
         ("card:Supporting Documents", "Supporting Documents", "Attach files with a title and click Attach."),
     ]},
    {"id": "monitoring-delete", "module": "monitoring", "user": AD, "url": "/app/monitoring/1/",
     "ops": [("click", button("Delete"))],
     "clip": "dialog[open]", "pad": 8,
     "caption": "Every deletion asks for confirmation",
     "markers": [
         ('dialog[open] >> role=button[name="Cancel"]', "Cancel", "Closes the dialog; nothing is deleted."),
         ('dialog[open] >> role=button[name^="Delete"]', "Delete Record", "Permanently deletes the record. This cannot be undone."),
     ],
     "after": [("press", "Escape")]},

    # ---------------------------------------------------------------- incoming
    {"id": "incoming-list", "module": "incoming", "user": AD, "url": "/app/incoming/",
     "caption": "Incoming Monitoring - the documents register",
     "markers": [
         (nav("Incoming Monitoring"), "Incoming Monitoring", "Sidebar entry."),
         (link("Monitoring dashboard"), "Monitoring dashboard", "The Division Chief's overview (Administrators)."),
         (link("Record Incoming Document"), "Record Incoming Document", "Records a newly received document."),
         ('main >> role=link[name="Monitoring reports"]', "Tabs", "Documents, Monitoring dashboard and Monitoring reports."),
         ("card:Total received", "Status figures", "Totals by status; overdue items are shown in red."),
         ("#filter-view", "View", "Quick lists such as Assigned to me, For Division Chief review, Awaiting acknowledgement, Overdue."),
         ("main tbody tr >> nth=0 >> role=link[name^=\"Open\"]", "Open", "Opens the document's record."),
     ]},
    {"id": "incoming-new", "module": "incoming", "user": EN, "url": "/app/incoming/new/", "height": 1150,
     "ops": [
         ("fill", "input[name=docket_number]", "2026-0101"),
         ("fill", "[name=subject]", "Request for technical assistance on the barangay development plan (sample)"),
         ("select", "select[name=document_type]", "Memorandum"),
         ("fill", "[name=source_office]", "Municipality of Tubay"),
         ("upload", "input[type=file]", str(SAMPLES / "sample-memorandum.pdf")),
     ],
     "clip": "main", "pad": 0,
     "caption": "Recording an incoming document (Encoder)",
     "markers": [
         ("field:DNS number", "DNS number", "Required. The document's number in the Document Numbering System."),
         ("field:Subject", "Subject", "Required."),
         ("field:Document type", "Document type", "Required."),
         ("field:Date received", "Date received", "Required. Defaults to today."),
         ("field:Source / office", "Source / office", "Required. Who sent it."),
         ("field:Document / file attachment", "Attachment", "The scanned document (optional)."),
         (button("Save"), "Save", "Records the document. It starts at For Division Chief review with no focal person."),
     ],
     "after": [("click", button("Save"))]},
    {"id": "incoming-recorded", "module": "incoming", "user": EN, "height": 1000,
     "caption": "The new record, awaiting the Division Chief's review",
     "markers": [
         ("[role=alert], [role=status] >> nth=0", "Confirmation", "Confirms the document was recorded."),
         ("card:Progress", "Progress", "Shows each stage; the current one is highlighted."),
         ("main h1", "LGMED code", "The record's identifier."),
     ]},
    {"id": "incoming-review-assign", "module": "incoming", "user": AD, "url": "/app/incoming/1/",
     "ops": [("scroll", "card:Division Chief", 20)], "height": 1000,
     "caption": "The Division Chief's review and assignment (Administrator)",
     "markers": [
         ("card:Division Chief", "Division Chief's Review", "Notes or instructions on what the document requires. Save review notes records them."),
         ("field:Focal person", "Focal person", "Required. The officer who will act on the document."),
         ("field:Priority", "Priority", "Low, Normal, High or Urgent."),
         ("field:Action due date", "Action due date", "When action is due; the document becomes overdue after this date."),
         (button("Assign and notify"), "Assign and notify", "Assigns the document and notifies the focal person."),
     ]},
    {"id": "incoming-acknowledge", "module": "incoming", "user": ST, "url": "/app/incoming/3/", "height": 1000,
     "caption": "The focal person acknowledges the assignment (LGMED Staff)",
     "markers": [
         (button("Acknowledge receipt"), "Acknowledge receipt", "Confirms you received the assignment. The document then continues in Outgoing Monitoring under its LGMED code."),
         ("card:Assignment", "Assignment", "Who assigned it, when, the priority, due date and the Chief's instructions."),
     ]},
    {"id": "incoming-dashboard", "module": "incoming", "user": AD, "url": "/app/incoming/dashboard/", "height": 1100,
     "caption": "Incoming Monitoring Dashboard (Administrators)",
     "markers": [
         ("card:Incoming document figures", "Figures", "Every figure is a link to the documents it counts."),
         ("card:Incoming Documents for Review", "For Review", "Documents still waiting for the Chief."),
         ("card:Overdue Documents", "Overdue Documents", "Past their action due date and not completed."),
         ("card:Documents by Focal Person", "Documents by Focal Person", "Workload per officer."),
     ]},
    {"id": "incoming-reports", "module": "incoming", "user": AD, "url": "/app/incoming/reports/", "height": 1100,
     "caption": "Monitoring Reports",
     "markers": [
         ("card:Reports", "Reports", "Ten ready-made reports. Click one to open it."),
         ("card:Filters", "Filters", "Narrow the report by text, dates, focal person, status, type; choose the sort order."),
         (button("Print"), "Print", "Prints the report."),
         (link("Export CSV"), "Export CSV", "Downloads the same rows as a spreadsheet file."),
     ]},

    # ---------------------------------------------------------------- outgoing
    {"id": "outgoing-list", "module": "outgoing", "user": ST, "url": "/app/outgoing/",
     "caption": "Outgoing Monitoring",
     "markers": [
         (nav("Outgoing Monitoring"), "Outgoing Monitoring", "Sidebar entry."),
         (link("Sync from Excel"), "Sync from Excel", "Imports historical records from the Outgoing spreadsheet (Data Sync)."),
         ("#filter-view", "View", "Assigned to me, For action (open), Action completed, Communication not yet sent, From the spreadsheet register."),
         SEARCH,
         ("main tbody tr >> nth=0 >> role=link[name^=\"Open\"]", "Open", "Opens the outgoing record."),
     ]},
    {"id": "outgoing-update", "module": "outgoing", "user": ST, "url": "/app/outgoing/2/", "height": 1100,
     "caption": "Reporting action on an assigned document (focal person)",
     "markers": [
         ("card:Action Progress", "Action Progress", "Where the document stands."),
         ("field:Action taken", "Action taken", "Required. What you did."),
         ("field:Current status", "Current status", "Required. In progress, For action, Pending or Completed - the update and the status change are one act."),
         ("field:Supporting attachment", "Supporting attachment", "Optional file, e.g. the reply sent."),
         (button("Record update"), "Record update", "Saves the update."),
         (link("Record communication sent"), "Record communication sent", "Records the reply or transmittal that was sent."),
     ]},
    {"id": "outgoing-return", "module": "outgoing", "user": AD, "url": "/app/outgoing/2/",
     "ops": [("scroll", "text=Return for revision", 30)],
     "clip": "card:Action and Updates", "pad": 10, "max_height": 1300,
     "caption": "Returning a document to the focal person (Division Chief)",
     "markers": [
         ("field:What needs revision", "What needs revision", "Required. Explain what must be revised."),
         (button("Return to focal person"), "Return to focal person", "Sends the document back; its status becomes Returned / for revision."),
     ]},
    {"id": "outgoing-sent", "module": "outgoing", "user": ST, "url": "/app/outgoing/2/sent/", "height": 1000,
     "clip": "main", "pad": 0,
     "caption": "Recording the communication sent",
     "markers": [
         ("field:Date sent", "Date sent", "Required. The date the reply or transmittal was sent."),
         ("field:Subject / title", "Subject / title", "Required. Filled in from the incoming document; change it if needed."),
         ("field:Sent to", "Sent to", "The addressee."),
         ("field:File of the communication", "File of the communication", "The communication as sent; it is filed in the Documents register with the incoming document."),
         (button("Save communication details"), "Save communication details", "Records the communication; Cancel returns without saving."),
     ]},

    # --------------------------------------------------------------- data sync
    {"id": "sync-home", "module": "datasync", "user": AD, "url": "/app/sync/?module=incoming", "height": 1000,
     "caption": "Data Sync - choosing the register and uploading the workbook",
     "markers": [
         (nav("Data Sync"), "Data Sync", "Sidebar entry (roles that may encode)."),
         ('main >> role=link[name^="Incoming"]', "Migration type", "Incoming keeps the register in step (new rows added, changed rows updated). Outgoing imports historical records once."),
         ("card:Columns read", "Columns read", "The column headings the sync recognises in the workbook."),
         ("field:Excel workbook", "Excel workbook", "Required. Choose the .xlsx file."),
         (button("Upload and preview"), "Upload and preview", "Reads every sheet and shows a preview. Nothing is saved yet."),
     ]},
    {"id": "sync-preview", "module": "datasync", "user": AD, "url": "/app/sync/?module=incoming", "height": 1100,
     "ops": [("upload", "input[type=file]", str(SAMPLES / "sample-incoming-register.xlsx")),
             ("click", button("Upload and preview")), ("wait", 2500)],
     "caption": "The preview of an uploaded workbook (illustrative sample file)",
     "markers": [
         ("card:Sheets", "Sheets", "Tick the sheets to include, then redraw the preview."),
         (button("Commit sync"), "Commit sync", "Saves the previewed rows to the register."),
         (button("Discard"), "Discard", "Throws the upload away; nothing is saved."),
     ]},

    # -------------------------------------------------------------------- lgus
    {"id": "lgus-list", "module": "lgus", "user": AD, "url": "/app/lgus/",
     "caption": "LGU Management - the directory of the 78 LGUs of Region XIII",
     "markers": [
         (nav("LGU Management"), "LGU Management", "Sidebar entry."),
         EXPORT,
         (link("Add LGU"), "Add LGU", "Adds an LGU to the directory."),
         SEARCH,
         ("#filter-compliance_status", "Compliance filter", "Compliant, Partially compliant, Non-compliant, Not yet assessed."),
         FIRST_ROW_VIEW,
         PAGER,
     ]},
    {"id": "lgus-detail", "module": "lgus", "user": AD, "url": "/app/lgus/1/",
     "caption": "An LGU profile",
     "markers": [
         ("card:LGU Profile", "LGU Profile", "Type, province, income class and compliance status."),
         ("card:Monitoring History", "Monitoring History", "Monitoring activities recorded for the LGU."),
         (link("New record"), "New record", "Records a monitoring activity."),
         ("card:Contact Information", "Contact Information", "The LGU's contact person and details."),
     ]},
    {"id": "lgus-new", "module": "lgus", "user": AD, "url": "/app/lgus/new/", "height": 1300, "clip": "main", "pad": 0,
     "caption": "New LGU form",
     "markers": [
         ("field:LGU name", "LGU name", "Required."),
         ("field:LGU type", "LGU type", "Required. Province, City or Municipality."),
         ("field:Province", "Province", "Required."),
         ("field:Compliance status", "Compliance status", "Required."),
         ("field:Active in the directory", "Active in the directory", "Untick to hide an LGU without deleting it."),
         (button("Save"), "Save", "Saves the LGU."),
     ]},

    # ---------------------------------------------------------------- services
    {"id": "services-list", "module": "services", "user": ST, "url": "/app/services/",
     "caption": "Frontline Services",
     "markers": [
         (nav("Frontline Services"), "Frontline Services", "Sidebar entry."),
         (link("Add Service"), "Add Service", "Adds a service."),
         ("#filter-is_published", "Publication filter", "Published or Not published on the public website."),
         TABLE,
     ]},
    {"id": "services-new", "module": "services", "user": ST, "url": "/app/services/new/", "height": 1200, "clip": "main", "pad": 0,
     "caption": "New Frontline Service form",
     "markers": [
         ("field:Service name", "Service name", "Required."),
         ("field:Service type", "Service type", "Required. Simple, Complex or Highly technical transaction."),
         ("field:Requirements", "Requirements", "What the client must bring."),
         ("field:Published on the public website", "Published on the public website", "Tick to list the service on the public website."),
         (button("Save"), "Save", "Saves the service."),
     ]},

    # ---------------------------------------------------------------- updates
    {"id": "updates-dashboard", "module": "updates", "user": ST, "url": "/app/updates/", "height": 1000,
     "caption": "Updates & Accomplishments - the division dashboard",
     "markers": [
         (nav("Accomplishments"), "Accomplishments", "Sidebar entry."),
         (link("Convocation view"), "Convocation view", "The presentation for the Monday convocation."),
         (link("Public disclosure"), "Public disclosure", "How much of the published record the public website shows (Chief / LGMED Staff)."),
         (link("Add Update"), "Add Update", "Contributes an entry to the Division's week."),
         ("main select[name=year]", "Year", "Changes the year the statistics cover."),
         ("card:This week", "This week", "The current reporting week and what it still lacks."),
     ]},
    {"id": "updates-new", "module": "updates", "user": EN, "url": "/app/updates/entries/new/", "height": 1600, "clip": "main", "pad": 0,
     "caption": "New Division Update form",
     "markers": [
         ("field:Reporting period", "Reporting period", "Required. The week the entry belongs to."),
         ("field:Title", "Title", "Required."),
         ("field:Category", "Category", "Required. Activity, communication, technical assistance, report, POPS Plan accomplishment or other."),
         ("field:Activity type", "Activity type", "Required. Conducted, Facilitated, Participated in, Attended, Meeting, Training - or Not an activity."),
         ("field:Status", "Status", "Required. Completed, Ongoing, Pending or Upcoming."),
         ("field:Date", "Date", "Required. Must fall inside the reporting week, except for Upcoming items."),
         (button("Save"), "Save", "Saves the entry to the week."),
     ]},
    {"id": "updates-entry", "module": "updates", "user": EN, "url": "/app/updates/entries/40/", "height": 1100,
     "caption": "An entry and its means of verification",
     "markers": [
         ("card:Means of Verification", "Means of Verification", "Evidence filed for the entry."),
         ("field:Type of evidence", "Type of evidence", "Required. Photograph, official document, report, certificate, attendance sheet, letter or other."),
         ("field:File", "File", "Required. The evidence file."),
         ("field:Cleared for the public website", "Cleared for the public website", "Only cleared evidence on a published week reaches the public website."),
         (button("File the evidence"), "File the evidence", "Attaches the file to the entry."),
     ]},
    {"id": "updates-week", "module": "updates", "user": EN, "url": "/app/updates/weeks/3/", "height": 1000,
     "caption": "A reporting week (open for contributions)",
     "markers": [
         (link("Convocation view"), "Convocation view", "Presentation view of the week."),
         (button("Submit for review"), "Submit for review", "Hands the week to the Division Chief."),
         (link("Add Update"), "Add Update", "Adds an entry."),
         ("card:The Division's Week", "The Division's Week", "Which of the seven parts of the week are recorded and which are still missing."),
     ]},
    {"id": "updates-review", "module": "updates", "user": AD, "url": "/app/updates/weeks/2/review/", "height": 1300,
     "caption": "The Division Chief's review of a week",
     "markers": [
         ("card:Remarks & Theme", "Remarks & Theme", "The week's theme and the Chief's remarks (Save remarks)."),
         ("card:Major Accomplishments to Present", "Major Accomplishments to Present", "Tick what leads the Monday convocation (Save selection)."),
         (button("Publish to the public website"), "Publish to the public website", "Publishes the cleared items of the week."),
         (button("Reopen for contributions"), "Reopen for contributions", "Returns the week to staff; withdraws it from the public website if it was published."),
     ]},
    {"id": "updates-convocation", "module": "updates", "user": AD, "url": "/app/updates/convocation/", "height": 1000,
     "caption": "The Monday Convocation view",
     "markers": [
         (link("Change the selection"), "Change the selection", "Returns to the review page to choose what is presented."),
         (button("Print"), "Print", "Prints the presentation."),
         ("card:Division Statistics", "Division Statistics", "The week's figures, typed large to be read from the back of a room."),
     ]},
    {"id": "updates-disclosure", "module": "updates", "user": AD, "url": "/app/updates/public-disclosure/", "height": 1300,
     "caption": "Public Disclosure Window",
     "markers": [
         ("field:What the public website shows", "What the public website shows", "Most recent completed weeks, most recent months, a fixed date range, or every published week."),
         ("field:Also show the week that is still running", "Week in progress", "Off by default: the running week is not shown publicly."),
         ("card:Showing Now", "Showing Now", "The weeks the current setting puts on the public website."),
         (button("Save"), "Save", "Saves the setting."),
     ]},

    # ----------------------------------------------------------- announcements
    {"id": "announcements-list", "module": "announcements", "user": ST, "url": "/app/announcements/",
     "caption": "Announcements",
     "markers": [
         (nav("Announcements"), "Announcements", "Sidebar entry."),
         (link("Add Announcement"), "Add Announcement", "Writes a news item, advisory, issuance, activity or commendation."),
         ("#filter-is_published", "Publication filter", "Published or Draft."),
         TABLE,
     ]},
    {"id": "announcements-new", "module": "announcements", "user": ST, "url": "/app/announcements/new/", "height": 1500, "clip": "main", "pad": 0,
     "caption": "New Announcement form",
     "markers": [
         ("field:Headline", "Headline", "Required."),
         ("field:Category", "Category", "Required."),
         ("field:Date published", "Date published", "Required. A future date keeps the item off the public site until that day."),
         ("field:Lead paragraph", "Lead paragraph", "Required. The summary shown on the news feed."),
         ("field:Photograph", "Photograph", "Optional image for the item."),
         ("field:Published on the public website", "Published on the public website", "Untick to keep the item as a draft."),
         ("field:Feature on the homepage", "Feature on the homepage", "Puts the item in the homepage's featured position."),
         (button("Save"), "Save", "Saves the item."),
     ]},

    # --------------------------------------------------------------- documents
    {"id": "documents-list", "module": "documents", "user": ST, "url": "/app/documents/",
     "caption": "Document Management - the register",
     "markers": [
         (nav("Document Management"), "Document Management", "Sidebar entry."),
         (link("Register Document"), "Register Document", "Registers a document."),
         ('main >> role=link[name="Retention & Archive"]', "Tabs", "Register, Monitoring, Files, and Retention & Archive."),
         ("#filter-view", "View", "Owned by me, Assigned to me, Not yet assigned, Overdue, Retention review due, Archived and more."),
         ("#filter-status", "Status", "Draft, Received, For review, For assignment, Assigned, In progress, For approval, Completed, Archived, Cancelled."),
         TABLE,
     ]},
    {"id": "documents-new", "module": "documents", "user": EN, "url": "/app/documents/new/", "height": 1500, "clip": "main", "pad": 0,
     "caption": "Register Document form",
     "markers": [
         ("field:Document title", "Document title", "Required."),
         ("field:Document type", "Document type", "Required. The type decides the retention period."),
         ("field:Action due date", "Action due date", "Optional; overdue documents are flagged."),
         ("field:Owner / responsible personnel", "Owner", "Required. The person answerable for the document."),
         ("field:Office / division", "Office / division", "Required."),
         ("field:Document file", "Document file", "The file (version 1)."),
         (button("Save"), "Save", "Registers the document and issues its control number."),
     ]},
    {"id": "documents-detail", "module": "documents", "user": ST, "url": "/app/documents/6/", "height": 1100,
     "caption": "A document record",
     "markers": [
         ("card:Document Lifecycle", "Document Lifecycle", "Each stage from registration to completion; the current stage is highlighted."),
         ("card:Document File", "Document File", "View or download the file, its version history, and upload a new version."),
         ("card:Review and Assignment", "Review and Assignment", "Review notes, the focal person and the Chief's instructions."),
         ("card:Actions", "Actions", "The next step for the document's current status (see Table)."),
     ]},
    {"id": "documents-assign", "module": "documents", "user": AD, "url": "/app/documents/8/",
     "ops": [("scroll", "card:Review and Assignment", 20)], "height": 1000,
     "caption": "Review and assignment of a document (Division Chief)",
     "markers": [
         ("card:Review and Assignment", "Review and Assignment", "The Chief names the focal person and gives instructions."),
         ("card:Retention", "Retention", "Record a retention decision: within period, for review, for disposal, or permanent preservation."),
     ]},
    {"id": "documents-monitoring", "module": "documents", "user": ST, "url": "/app/documents/monitoring/", "height": 1100,
     "caption": "Document Monitoring",
     "markers": [
         ("card:Document counts", "Document counts", "Each figure is a link to the documents it counts."),
         ("card:Awaiting action", "Awaiting action", "Documents waiting at each stage."),
         ("card:Overdue documents", "Overdue documents", "Past their action due date."),
     ]},
    {"id": "documents-files", "module": "documents", "user": ST, "url": "/app/documents/files/",
     "caption": "Document Files - every stored file in one list",
     "markers": [
         ("field:Source", "Source", "Incoming document, Focal person's update, Outgoing communication, or Registered here."),
         (button("Search"), "Search", "Runs the search."),
         ('main >> role=link[name^="Download"] >> nth=0', "Download", "Downloads the file. Every download is recorded on the document's trail."),
     ]},
    {"id": "documents-retention", "module": "documents", "user": ST, "url": "/app/documents/retention/", "height": 1100,
     "caption": "Retention and Archive",
     "markers": [
         (link("Browse the archive"), "Browse the archive", "Lists archived documents."),
         ("card:Retention review due", "Retention review due", "Documents whose retention period has run out."),
         ("card:Retention schedule", "Retention schedule", "The retention period of each document type."),
     ]},
    {"id": "documents-archive", "module": "documents", "user": ST, "url": "/app/documents/17/",
     "ops": [("click", button("Archive document"))],
     "clip": "dialog[open]", "pad": 8,
     "caption": "Archiving a completed document",
     "markers": [
         ("field:Reason for archiving", "Reason for archiving", "Why the document is being archived."),
         ('dialog[open] >> role=button[name="Archive document"]', "Archive document", "Archives it. Nothing is deleted; access is restricted and it leaves the public website."),
     ],
     "after": [("press", "Escape")]},

    # ---------------------------------------------------------------- analytics
    {"id": "analytics-page", "module": "analytics", "user": ST, "url": "/app/analytics/", "height": 1000,
     "caption": "Analytics",
     "markers": [
         (nav("Analytics"), "Analytics", "Sidebar entry."),
         ("main select[name=year]", "Year", "The year analysed."),
         (link("Export CSV"), "Export CSV", "Downloads the figures."),
         (button("Print"), "Print", "Prints the page."),
         ("card:Headline figures", "Headline figures", "Coverage, trend and turnaround for the year."),
     ]},
    {"id": "analytics-least", "module": "analytics", "user": ST, "url": "/app/analytics/",
     "ops": [("scroll", "card:Least-Monitored LGUs", 20)], "height": 1000,
     "caption": "Least-Monitored LGUs",
     "markers": [
         ("card:Least-Monitored LGUs", "Least-Monitored LGUs", "LGUs the Division has reached least, in the order to reach them."),
         ('main >> role=link[name^="Schedule monitoring for"] >> nth=0', "Schedule monitoring", "Opens a new monitoring record."),
     ]},

    # ----------------------------------------------------------------- reports
    {"id": "reports-list", "module": "reports", "user": ST, "url": "/app/reports/",
     "caption": "Reports",
     "markers": [
         (nav("Reports"), "Reports", "Sidebar entry."),
         (link("Add Report"), "Add Report", "Adds a report."),
         ("#filter-status", "Status", "Draft, Submitted, For review, Approved, Published, Returned."),
         TABLE,
     ]},
    {"id": "reports-new", "module": "reports", "user": ST, "url": "/app/reports/new/", "height": 1300, "clip": "main", "pad": 0,
     "caption": "New Report form",
     "markers": [
         ("field:Report title", "Report title", "Required."),
         ("field:Reporting period", "Reporting period", "Required. Monthly, Quarterly, Semestral, Annual or Special report."),
         ("field:Year", "Year", "Required."),
         ("field:File", "File", "The report file."),
         ("field:Status", "Status", "Required. Where the report stands in review."),
         (button("Save"), "Save", "Saves the report."),
     ]},
    {"id": "reports-detail", "module": "reports", "user": ST, "url": "/app/reports/9/",
     "caption": "A report and its review workflow",
     "markers": [
         ("card:Review Workflow", "Review Workflow", "Draft, Submitted, For review, Approved, Published."),
         ("card:Report Summary", "Report Summary", "Summary, file and any review remarks."),
         (link("Edit"), "Edit", "Changes the report, including its status."),
     ]},

    # ---------------------------------------------------------------- calendar
    {"id": "calendar-month", "module": "calendar", "user": AD, "url": "/app/calendar/?scope=all", "height": 1000,
     "caption": "The Calendar (All employees, month view)",
     "markers": [
         (nav("Calendar"), "Calendar", "Sidebar entry."),
         (link("Add Activity"), "Add Activity", "Opens the full activity form."),
         ('main >> role=link[name="My calendar"]', "Scope", "My calendar, Assigned to me, Shared with me, All employees (supervisors)."),
         ('main >> role=link[name="Week"]', "Period", "Month, Week, Upcoming, Overdue."),
         ('main >> role=link[name=/^Previous month/]', "Month navigation", "Previous and next month."),
         ("main table", "Month grid", "Click anywhere in a day to see everything on it and add an activity for that day."),
     ]},
    {"id": "calendar-day", "module": "calendar", "user": ST, "url": "/app/calendar/",
     "ops": [("click", 'main td a[href*="day="] >> nth=12'), ("wait", 600)],
     "clip": "dialog[open]", "pad": 8, "max_height": 2000, "height": 1700,
     "caption": "The day dialog - quick add for the selected day",
     "markers": [
         ("field:Title", "Title", "Required."),
         ("field:Activity type", "Activity type", "Required."),
         ("dialog[open] select[name=visibility]", "Visibility", "Required. Private (only you and your supervisors), Assigned users, Team or Organization-wide."),
         ('dialog[open] >> role=button[name="Save activity"]', "Save activity", "Saves the activity on that day."),
     ],
     "after": [("press", "Escape")]},
    {"id": "calendar-new", "module": "calendar", "user": ST, "url": "/app/calendar/new/", "height": 1700, "clip": "main", "pad": 0,
     "caption": "New Activity form",
     "markers": [
         ("field:Title", "Title", "Required."),
         ("field:Assigned to", "Assigned to", "The person doing it when that is not the owner."),
         ("field:Start date", "Start date", "Required."),
         ("field:Visibility", "Visibility", "Required. Defaults to Private."),
         ("field:Show on the public calendar", "Show on the public calendar", "Allowed only for Organization-wide activities."),
         (button("Save"), "Save", "Saves the activity."),
     ]},
    {"id": "calendar-detail", "module": "calendar", "user": AD, "url": "/app/calendar/1/",
     "caption": "An activity record",
     "markers": [
         ("card:Ownership", "Ownership", "Owner, assignee and section."),
         ("card:Report progress", "Report progress", "The owner or assignee updates the status and remarks, then clicks Save update."),
         ("card:Visibility", "Visibility", "Who may see the activity."),
     ]},
    {"id": "calendar-monitor", "module": "calendar", "user": AD, "url": "/app/calendar/monitor/", "height": 1000,
     "caption": "Activity Monitoring (Division Chief)",
     "markers": [
         (nav("Activity Monitoring"), "Activity Monitoring", "Sidebar entry for supervisors."),
         ("card:Workload by employee", "Workload by employee", "Open, upcoming, overdue, assigned and completed counts per employee."),
         (link("All employees' calendar"), "All employees' calendar", "Opens everyone's activities."),
     ]},

    # ----------------------------------------------------------- public site
    {"id": "publicsite-admin", "module": "publicsite", "user": ST, "url": "/app/settings/public-site/", "height": 1100,
     "caption": "Public Website management",
     "markers": [
         (nav("Public Website"), "Public Website", "Sidebar entry (Administrators and LGMED Staff)."),
         ("card:What the public can see", "What the public can see", "What is published right now, counted from the records. Manage opens the module."),
         ("card:Website text", "Website text", "The homepage heading, mandate, office details and standing notices."),
     ]},
    {"id": "publicsite-home", "module": "publicsite", "user": None, "url": "/",
     "caption": "The public website homepage",
     "markers": [
         ("header nav, nav >> nth=0", "Public navigation", "Home, News, Accomplishments, Programs, Frontline Services, Statistics, Reports, Document Library, Calendar, About, Contact."),
     ]},

    # -------------------------------------------------------------- admin
    {"id": "users-list", "module": "administration", "user": AD, "url": "/accounts/users/",
     "caption": "Users & Roles",
     "markers": [
         (nav("Users & Roles"), "Users & Roles", "Sidebar entry (Administrators)."),
         (link("Roles & permissions"), "Roles & permissions", "The permission matrix."),
         (link("Add Account"), "Add Account", "Creates a user account."),
         ("#filter-role", "Role filter", "Narrows the list by role."),
         TABLE,
     ]},
    {"id": "users-new", "module": "administration", "user": AD, "url": "/accounts/users/new/", "height": 1300, "clip": "main", "pad": 0,
     "caption": "New User Account form",
     "markers": [
         ("field:Username", "Username", "Required."),
         ("field:Email address", "Email address", "Required."),
         ("field:Initials for LGMED codes", "Initials for LGMED codes", "Used in LGMED control codes (e.g. middle initial included)."),
         ("field:Role", "Role", "Required. System Administrator, Administrator, LGMED Staff, Encoder or Viewer."),
         ("field:Active", "Active", "Untick to create the account deactivated."),
         (button("Save"), "Save", "Creates the account."),
     ]},
    {"id": "users-detail", "module": "administration", "user": AD, "url": "/accounts/users/3/",
     "caption": "A user account",
     "markers": [
         (link("Reset password"), "Reset password", "Sets a new password for the user."),
         (link("Edit"), "Edit", "Changes the account details and role."),
         (button("Deactivate"), "Deactivate", "Blocks sign-in. Accounts are never deleted, so their history stays attributable."),
         (link("Full audit trail"), "Full audit trail", "Everything this person did, in the audit log."),
     ]},
    {"id": "users-roles", "module": "administration", "user": AD, "url": "/accounts/roles/", "height": 1300,
     "caption": "Roles & Permissions - the permission matrix",
     "markers": [
         ("card:Permission Matrix", "Permission Matrix", "Which role holds which permission, generated from the rules the system enforces."),
     ]},
    {"id": "users-menu-permissions", "module": "administration", "user": SA, "url": "/accounts/menu-permissions/", "height": 1100,
     "caption": "Menu Permissions (System Administrator only)",
     "markers": [
         (nav("Menu Permissions"), "Menu Permissions", "Sidebar entry for the System Administrator."),
         ("card:Modules by Role", "Modules by Role", "Tick or untick which modules each role is offered; Save role permissions."),
         (button("Save role permissions"), "Save role permissions", "Saves the matrix."),
     ]},
    {"id": "settings-page", "module": "administration", "user": AD, "url": "/app/settings/", "height": 1200,
     "caption": "System Settings",
     "markers": [
         ("card:Preferences", "Preferences", "Records per page, session warning, system notice and the public website switch."),
         (button("Save settings"), "Save settings", "Saves the preferences."),
         ("card:Program categories", "Reference lists", "Program categories, document types, sections, disposal authorities, provinces. Add / Edit / Remove."),
     ]},
    {"id": "audit-list", "module": "administration", "user": AD, "url": "/app/audit-logs/",
     "caption": "Audit Logs",
     "markers": [
         (nav("Audit Logs"), "Audit Logs", "Sidebar entry (Administrators)."),
         ("field:From date", "Date range", "From date and To date; click Apply dates."),
         ("field:Only entries needing attention", "Needing attention", "Failed sign-ins, refused access and similar."),
         ("#filter-action", "Filters", "Action, Record type and Actor."),
         TABLE,
     ]},

    # ------------------------------------------------------------------ e-SIRA
    {"id": "esira-dashboard", "module": "esira", "user": EN, "url": "/app/esira/",
     "caption": "e-SIRA dashboard",
     "markers": [
         ('#sidebar >> role=link[name*="e-SIRA"]', "e-SIRA", "LGMED Innovation Action, pinned at the foot of the sidebar."),
         ('main >> role=link[name="Documents"] >> nth=0', "e-SIRA menu", "Dashboard, Documents, My Digital Certificate, My Signature Style (and, for administrators, Certificate Verification and Audit Trail)."),
         (link("Upload / Scan Document"), "Upload / Scan Document", "Starts a new document."),
         (link("My certificates"), "My certificates", "Your PNPKI certificate and signature image."),
         ("card:Waiting on Me", "Waiting on Me", "Documents whose next step is yours."),
     ]},
    {"id": "esira-upload", "module": "esira", "user": EN, "url": "/app/esira/documents/new/", "height": 1100,
     "ops": [("fill", "input[name=title]", "Sample memorandum for signature (illustrative)"),
             ("upload", "input[type=file] >> nth=0", str(SAMPLES / "sample-memorandum.pdf"))],
     "clip": "main", "pad": 0,
     "caption": "Upload or Scan a Document",
     "markers": [
         ("field:Title", "Title", "Required."),
         ("field:How is the document coming in?", "How is the document coming in?", "Upload a PDF, or Scan pages (images from a scanner or phone camera)."),
         ("field:PDF file", "PDF file", "The PDF to be signed or routed."),
         (button("Upload and prepare"), "Upload and prepare", "Uploads the file and opens the signing workspace."),
     ],
     "after": [("click", button("Upload and prepare"))]},
    {"id": "esira-workspace", "module": "esira", "user": EN, "height": 1000, "wait": 2500,
     "caption": "The signing workspace - preview and signature boxes",
     "markers": [
         (button("Zoom in"), "Zoom and pages", "Zoom, fit width and move between pages."),
         ("card:Signature Boxes", "Signature Boxes", "Choose the signer for new boxes, then Add Signature Box and drag it into place."),
         (button("Add Signature Box"), "Add Signature Box", "Places a box on the current page."),
         (link("Route for signature"), "Route for signature", "Chooses who signs or approves, and in what order."),
     ]},
    {"id": "esira-route", "module": "esira", "user": EN, "height": 1000,
     "ops": [("click", link("Route for signature"))],
     "clip": "main", "pad": 0,
     "caption": "Routing the document",
     "markers": [
         ("main select[name$=recipient] >> nth=0", "Recipient", "The person for this step."),
         ("main select[name$=action] >> nth=0", "Action required", "Signature, Approval, Review / initials, or For information / acknowledgement."),
         (button("Add a step"), "Add a step", "Adds another recipient; steps run in order."),
         (button("Send on route"), "Send on route", "Sends the document to the first recipient."),
     ]},
    {"id": "esira-route-filled", "module": "esira", "user": EN, "height": 1000,
     "ops": [("select_value", "main select[name$=recipient] >> nth=0", "2"),
             ("select_value", "main select[name$=action] >> nth=0", "APPROVE"),
             ("fill", "main input[name$=purpose] >> nth=0", "Please approve the attached sample memorandum.")],
     "clip": "main", "pad": 0,
     "caption": "A one-step route: the Division Chief is asked to approve",
     "markers": [
         ("main select[name$=recipient] >> nth=0", "Recipient", "Antonio Villanueva (Division Chief) is chosen."),
         ("main select[name$=action] >> nth=0", "Action required", "Approval."),
         ("main input[name$=purpose] >> nth=0", "Purpose / instructions", "What the recipient is asked to do."),
         (button("Send on route"), "Send on route", "Sends the document."),
     ],
     "after": [("click", button("Send on route"))]},
    {"id": "esira-act", "module": "esira", "user": AD, "url": "/app/esira/documents/1/", "height": 1000,
     "caption": "The recipient acts on a routed document (Division Chief)",
     "markers": [
         ("card:Status", "Status", "Where the document stands and what is asked of you."),
         (button("Approve"), "Approve", "Completes your step (Mark reviewed or Acknowledge for those step types)."),
         (button("Reject and return"), "Reject and return", "Stops the route and returns the document to its owner."),
         ("card:Routing History", "Routing History", "Every step: when it was routed, received and acted on."),
     ]},
    {"id": "esira-certificate", "module": "esira", "user": ST, "url": "/app/esira/certificates/", "height": 1100,
     "caption": "My Digital Certificate",
     "markers": [
         ("card:My Digital Certificate", "Digital certificate", "Upload your DICT PNPKI .p12 file and its password."),
         ("field:Require .p12 password when signing", "Require password when signing", "Recommended. Asks for the password each time you sign."),
         (button("Save certificate"), "Save certificate", "Registers the certificate. An administrator must verify it before you can sign."),
         ("card:My Registered Certificates", "My Registered Certificates", "Your certificates and their verification status."),
     ]},
    {"id": "esira-styles", "module": "esira", "user": ST, "url": "/app/esira/signature-styles/",
     "caption": "My Signature Style",
     "markers": [
         (button("Add custom style"), "Add custom style", "Adds a graphic style (up to 10)."),
     ]},
    {"id": "esira-verification", "module": "esira", "user": AD, "url": "/app/esira/certificates/verification/",
     "caption": "PNPKI Certificate Verification (Administrators)",
     "markers": [
         ("card:Awaiting Verification", "Awaiting Verification", "Certificates registered by employees. Compare name, e-mail and serial number with the PNPKI issuance record, then Verify."),
         ("card:Reviewed Certificates", "Reviewed Certificates", "Verified or rejected certificates; a verified one can be revoked."),
     ]},
    {"id": "esira-documents", "module": "esira", "user": EN, "url": "/app/esira/documents/",
     "caption": "e-SIRA Documents",
     "markers": [
         ('main >> role=link[name="Awaiting my signature"]', "Views", "Awaiting my signature, Waiting on me, Owned by me, Out for signature and more."),
         ("#filter-status", "Status", "Draft through Completed, Rejected or Cancelled."),
         TABLE,
     ]},

    # ------------------------------------------------------------------ errors
    {"id": "errors-403", "module": "errors", "user": VW, "url": "/app/monitoring/new/",
     "caption": "The page shown when your role does not permit an action",
     "markers": [("main h1", "Access denied", "The action is not available to your role. Use the sidebar to return.")]},
]
