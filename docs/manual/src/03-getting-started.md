# 4. System Requirements and Supported Browsers

| Requirement | Details |
|---|---|
| Device | A desktop or laptop computer is recommended for data entry. The interface also adapts to tablets and phones (the sidebar becomes a menu button). |
| Browser | A current version of **Google Chrome** or **Microsoft Edge** (recommended; the screenshots in this manual were taken in Chrome). Current versions of Mozilla Firefox and Safari can also be used. |
| JavaScript | Must be switched on. The sign-in page uses JavaScript for its security check and shows a notice if it is switched off. |
| Network | Access to the office network or the address the system administrator gives you. If the sign-in security check (reCAPTCHA) is enabled, the browser must also be able to reach `www.google.com`. |
| Account | A user account issued by the system administrator. |
| For two-step verification | An authenticator app on your phone (for example Google Authenticator or Microsoft Authenticator). Required for Administrators and System Administrators. |
| For digital signing (e-SIRA) | Your DICT PNPKI digital certificate file (.p12 or .pfx) and its password. |
| For viewing files | PDF files open inside the system's own viewer; other file types are downloaded and opened with the usual program (Word, Excel, an image viewer). |

> **NOTE:** The system can be installed as an app from the browser (account menu › **Install app**) where the browser supports it. Installation needs a secure (HTTPS) address. See Section 7.9.

# 5. Accessing the System

LGMED-IMMS has two parts:

| Part | Address | Who uses it |
|---|---|---|
| Public website | The site's home address, for example `https://<server>/` | Anyone. It shows news, accomplishments, programs, frontline services, statistics, reports, the document library, the calendar, About and Contact. |
| Internal system | `https://<server>/staff` (which opens `/accounts/login/`) | DILG Caraga LGMED personnel with an account. |

**Nothing on the public website links to the staff sign-in page.** Type the address yourself or use a bookmark.

### Procedure 5.1: Open the sign-in page

**Purpose:** Reach the staff sign-in page.

**Who can do this:** Anyone with a user account.

**Steps:**

1. Open Google Chrome or Microsoft Edge.
2. In the address bar, type the system's address followed by `/staff` (for example `https://<server>/staff`) and press **Enter**. Your system administrator will tell you the server address.
3. Bookmark the page so you can return to it easily.

**Expected Result:** The sign-in page (Figure {{ref:access-login}}) opens.

**Important Notes:** If the page does not open, see Chapter 15, *Troubleshooting*.

# 6. Logging In and Logging Out

{{figure:access-login}}

### Procedure 6.1: Sign in

**Purpose:** Start a session in LGMED-IMMS.

**Who can do this:** All roles.

**Steps:**

1. Open the sign-in page (Procedure 5.1).
2. Type your username in **Username** (marker 1).
3. Type your password in **Password** (marker 2). Click the eye button to check what you typed. A message warns you if Caps Lock is on.
4. Click **Sign in** (marker 4).
5. If your account has two-step verification, the system asks for an **Authentication code**. Open your authenticator app and type the six-digit code it shows for LGMED-IMMS, then continue. If you no longer have your phone, use one of your **recovery codes** instead.
6. The first time you sign in, read the **Data Privacy Notice** and accept it (Procedure 6.2).

**Expected Result:** The **Dashboard** opens. If you were sent to the sign-in page from a link, the system takes you to the page you originally asked for.

**Important Notes:**

- If the username or password is wrong, the page shows **Sign-in unsuccessful**. Check both and try again. Failed sign-ins are recorded in the audit log.
- **Administrators must use two-step verification.** If an Administrator account has not yet set it up, the system leads the user through setup at sign-in.
- If **Forgot password?** (marker 3) is clicked, an e-mail addressed to the office opens so you can request a reset. Passwords are reset by an administrator (Section 10.17).

{{figure:access-privacy}}

### Procedure 6.2: Accept the Data Privacy Notice

**Purpose:** Confirm that you understand your obligations under the Data Privacy Act of 2012 (Republic Act No. 10173) before using records that contain personal information.

**Who can do this:** All roles, at first sign-in.

**Steps:**

1. Read the notice. It explains (1) what the system collects, (2) your obligations as a user, (3) the rights of data subjects and (4) monitoring and penalties. Scroll inside the notice to read every section.
2. Tick **I have read and understood this notice, and I agree to use LGMED-IMMS in accordance with the Data Privacy Act of 2012 (Republic Act No. 10173)** (marker 2).
3. Click **I Agree and Continue** (marker 4).

**Expected Result:** The notice closes and the system can be used. It is not shown again unless the notice is changed.

**Important Notes:** **Decline and sign out** (marker 3) signs you out. You cannot use the system without accepting the notice.

{{figure:access-account-menu}}

### Procedure 6.3: Sign out

**Purpose:** End your session so nobody else can use your account.

**Who can do this:** All roles.

**Steps:**

1. Click your name at the top right of the screen (**Account menu**, marker 1).
2. Click **Sign out** (marker 4).

**Expected Result:** The session ends and the sign-in page is shown.

**Important Notes:**

- Always sign out before leaving a shared or public computer.
- Your session also ends when you **close the browser**, and after **eight hours without activity**. A warning appears a few minutes before the session expires (the number of minutes is set by the administrator; the default is 5). Save your work when you see it.
