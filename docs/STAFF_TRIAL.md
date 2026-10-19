# Staff trial on the office network

**Purpose:** a week or two of real people using LGMED-IMMS for their real
kinds of work, on **demonstration data**, before anything real is entered.
Problems found here cost an afternoon; found after go-live they cost records.

**Who:** the System Administrator runs it; one or two people from each role
take part (Encoder, LGMED Staff, the Division Chief or an Administrator, and a
Viewer if the office uses that role).

**Nothing in the trial is real.** Testers may make up documents, upload any
harmless file, and break things. Do not enter real personal information.

---

## 1. Set it up (System Administrator)

1. On the PC that runs the system, start it for the office network:

   ```powershell
   .\run-lan.ps1
   ```

   It prints the address to give testers, for example `http://192.168.1.25:8000/staff`.
   Keep the window open for as long as testers are working; the PC must stay on
   and connected.

2. Sign in as yourself, open **Users & Roles › Add Account**, and create an
   account **for each tester**, with their own e-mail address and the role they
   will have for real. They receive a temporary password by e-mail - which is
   itself part of the trial. (If e-mail is not set up on this PC, the password
   is shown to you once: give it to the tester in person.)

3. Tell testers before they start:
   - the address, and that they will receive an e-mail;
   - **LGMED Staff and Administrators: install Google Authenticator or
     Microsoft Authenticator on your phone first** - you will be asked to set
     it up at your first sign-in;
   - the manual: `docs/manual/system-user-manual.pdf`;
   - how to report a problem (Section 3).

4. Give each tester the checklist for their role (Section 2), printed or as
   this page.

> Do not use the demonstration accounts (`lgmed.admin`, `lgmed.staff`, ...) for
> the trial: their password is published, and testing the new-account steps is
> part of the point.

## 2. What each tester tries

Tick what worked; write down what did not (Section 3). Every tester:

- [ ] Signs in with the temporary password from the e-mail, chooses their own
      password, and accepts the privacy notice.
- [ ] (LGMED Staff and Administrators) Sets up the authenticator app, saves the
      recovery codes, signs out and back in with a code.
- [ ] Opens **My profile**: changes their password once; looks at **Where You
      Are Signed In**; signs in from a second browser or their phone, then uses
      **Sign out other devices**.
- [ ] Tries **Appearance › Dark** and back to **Light**.
- [ ] Opens the system on their phone and finds their way around one list.
- [ ] Reads **My Work** on the Dashboard after something is assigned to them.

### Encoder

- [ ] Records an incoming document with an attached PDF.
- [ ] After the Chief assigns one to them: acknowledges it (try **Acknowledge
      ticked** with two at once), then records an update and the communication
      sent in **Outgoing Monitoring**.
- [ ] Registers a document in **Document Management**, once **Internal** and
      once **Confidential**; asks a colleague whether they can see each.
- [ ] Records a monitoring activity with an attachment.
- [ ] Uploads their MMIA and DTR for the month in **Monthly Submissions**.
- [ ] Adds a calendar activity and reports progress on it.

### LGMED Staff

Everything an Encoder does, plus:

- [ ] Reviews a programme/project record in **PPA Review Queue** and approves
      or returns it.
- [ ] Approves a report.
- [ ] Records the week's accomplishments in **Accomplishments**.
- [ ] Registers their PNPKI test certificate in **e-SIRA › My Digital
      Certificate** (if they have one) and, once verified, signs a document.

### Division Chief / Administrator

- [ ] Reviews an incoming document and assigns a focal person with a due date.
- [ ] Follows the caseload on **Incoming › Monitoring dashboard**.
- [ ] Sets the month's MMIA/DTR deadline and watches submissions come in.
- [ ] Creates a tester's account (Section 1.2) and **resets** one tester's
      password; the tester confirms the e-mail arrived and they had to change it.
- [ ] Opens a document a tester marked **Confidential**.
- [ ] Verifies a tester's e-SIRA certificate; routes a document for signature.
- [ ] Searches the **Audit Logs** for what a tester did.
- [ ] Sends themselves the weekly summary:
      `venv\Scripts\python manage.py send_weekly_summary --force`

### Viewer

- [ ] Finds a record by search and filters; opens and downloads its file.
- [ ] Confirms there is nothing they can change.
- [ ] Acts on an e-SIRA document routed to them.

## 3. Reporting a problem

One line per problem, in a shared spreadsheet or on paper:

| # | Who / role | Page (copy the address) | What I did | What I expected | What happened | Screenshot? |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

Also note what was **confusing**, not only what was broken: a button that was
hard to find is worth a line.

The System Administrator collects the list at the end of each day, and the
fixes are made before go-live.

## 4. Afterwards

- [ ] The problems list is worked through; each is fixed, explained, or
      deliberately left.
- [ ] Testers' feedback on the manual is folded into `docs/manual/src/`.
- [ ] **Nothing from the trial is carried to the real server.** Go-live starts
      from an empty database (docs/GO_LIVE.md, step 3); testers get new real
      accounts there.
