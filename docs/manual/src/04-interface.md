# 7. User Interface Overview

Every internal page has the same frame, so once you know one page you know where to find things on all of them.

{{figure:ui-layout}}

## 7.1 The top bar

- **System banner** (marker 1): *Department of the Interior and Local Government • Regional Office XIII – Caraga* on the left, *Secure internal system — for authorized personnel only* on the right.
- **Search records** (marker 2): a quick search box. On module list pages, use the module's own search box (Section 7.4), which searches that module's records.
- **Notifications bell** (marker 3): the red badge shows how many notifications you have not read. Click the bell to see the latest; see Chapter 12.
- **Account menu** (marker 4): your name and position. It opens **My profile**, **Design system** (a reference page of interface components), **Public website**, **Install app** (where the browser supports it) and **Sign out** (Figure {{ref:access-account-menu}}).

{{figure:ui-notification-bell}}

## 7.2 The sidebar

The sidebar on the left lists the modules in groups: **Main**, **Information**, **Administration** (Administrators only) and, pinned at the bottom, **LGMED Innovation Action** (e-SIRA). The item for the page you are on is highlighted (marker 6).

> **IMPORTANT:** The sidebar shows only the modules your role allows (Chapter 9), and the System Administrator can close further modules to a role or to a single account (Section 10.17). A module that is not in your sidebar is not available to you; typing its address shows an *access denied* page.

On a narrow screen (tablet or phone) the sidebar is hidden. Tap the menu button at the top left to open it.

## 7.3 The page header

Under the top bar, each page shows:

- the **breadcrumb** (marker 8) — the path to the current page; click an earlier part to go back;
- the **page title** and a short description (marker 9);
- the **page actions** (marker 10) — buttons for the main tasks on that page, such as **New monitoring record**, **Export CSV** or **Add LGU**.

## 7.4 Lists of records

Most modules open on a list (a *register*). All lists work the same way (Figure {{ref:monitoring-list}}):

| Control | How to use it |
|---|---|
| **Search box** | Type part of a title, name, code or other text and press **Enter** or click **Apply**. |
| **Filters** | Drop-down lists (for example *Status: All*, *Province: All*). Choose a value and click **Apply**. Filters can be combined with the search. |
| **Date range** | Some lists have **From** and **To** dates; some let you choose which date the range applies to (for example *Date received* or *Date completed*). |
| **Sortable headings** | Click an underlined column heading to sort by it; click again to reverse the order. |
| **Row actions** | The eye icon (**View** / **Open**), pencil (**Edit**) and bin (**Delete**) at the end of each row. Only the actions your role may perform are shown. |
| **Pagination** | **Previous** / **Next** and page numbers at the foot of the list. The number of rows per page is set by the administrator (default 15). |
| **Export CSV** | Downloads the rows that match the current search and filters as a CSV file that opens in Excel. Every export is recorded in the audit log. |

## 7.5 Record pages

Opening a record shows its details in panels (*cards*). Common elements:

- **Back to list** returns to the register.
- **Print** prints the record in a print-friendly layout.
- **Edit** opens the form; **Delete** asks for confirmation first (Figure {{ref:monitoring-delete}}).
- **Progress** / **Lifecycle** shows each stage of the record's workflow, with the current stage highlighted.
- **Record Information** shows who created the record and who last changed it, and when.
- **Audit Trail** / **Record trail** / **Document Trail** lists what happened to the record, by whom and when.

## 7.6 Forms

- Required fields are marked with a red asterisk (**\***). The note *\* indicates a required field* appears at the bottom of each form.
- Grey text under a field explains what to enter.
- **Save** stores the record; **Cancel** returns without saving.
- If something is wrong, the form is shown again with the problem written in red under the field (Chapter 13).

## 7.7 Status labels

Statuses are shown as coloured labels that also carry a symbol and a word, so they can be read without relying on colour: for example **Completed** (green, tick), **In progress** (blue), **Overdue** and **Returned / for revision** (red, warning sign).

## 7.8 Viewing PDF files

PDF files open in the system's built-in viewer inside the page. Other files are downloaded. Files are never served from a public address: every view and download is checked against your access and, in Document Management, recorded on the document's trail.

## 7.9 Installing the system as an app

Where the browser supports it (Chrome or Edge on Windows and Android; *Add to Home Screen* on iPhone/iPad), LGMED-iMMS can be installed as an app.

### Procedure 7.1: Install LGMED-iMMS as an app

**Purpose:** Open the system from its own icon, like a desktop or phone app.

**Who can do this:** All roles.

**Steps:**

1. Sign in.
2. Open the **Account menu** at the top right.
3. Click **Install app**. (On iPhone or iPad, follow the on-screen instructions to use **Share › Add to Home Screen**.)
4. Confirm the installation in the browser's prompt.

**Expected Result:** An LGMED-iMMS icon is added to the desktop, Start menu or home screen.

**Important Notes:** **Install app** only appears when the browser can install the system, which requires a secure (HTTPS) address. The app keeps only the screen design and an offline notice on the device — never your records. You still need to be online and signed in.
