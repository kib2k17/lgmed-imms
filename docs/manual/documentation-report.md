# Documentation Progress Report — LGMED-IMMS System User Manual

**Edition:** 1.0 · **Date:** 8 October 2026 · **System build documented:** commit `3129cb5` (branch `main`)

## 1. Summary

| Item | Result |
|---|---|
| Modules discovered | 24 module groups (31 including sub-modules) — see `module-inventory.md` |
| Modules documented | All 24, each with overview, annotated screenshots and procedures |
| Procedures written | 78, in the required format (Purpose, Who, Steps, Expected Result, Visual Reference, Important Notes) |
| Screenshots captured | **87**, all from the live application; every numbered marker located on the real control (0 missing) |
| Workflow diagrams | 6 (overview, incoming/outgoing, documents, PPA publication, weekly accomplishments, e-SIRA) |
| Outputs | `system-user-manual.pdf` (170 pp, A4), `.docx` (Word, ~140 pp), `.pptx` (131 slides), `.md`, `.html` |
| PDF checks | Every page has selectable/searchable text; 61 bookmarks, each verified to land on its heading; table of contents carries real page numbers and is clickable; figure cross-references are links; no blank pages |
| Build consistency checks | 0 problems: every `{{figure}}`/`{{ref}}` token resolves, every captured figure is used, every marker found, every image file exists |

## 2. How the screenshots were obtained (and what they are not)

- Captured with `build/capture.py` (Playwright driving Google Chrome) from the **real application code** in this repository, running as a **separate documentation instance** (`build/docs_settings.py`): a fresh SQLite database under `C:\lgdt`, seeded only with the project's own `seed_lgus`, `bootstrap_demo` and `seed_records` demonstration data. **The office's MySQL database, `media/` and `protected/` were never touched**, and no live records appear in the manual.
- On that instance only, two sign-in protections are switched off so the script can sign in as each demonstration role: the **reCAPTCHA** check (so the sign-in page in Figure 2 shows no reCAPTCHA badge) and the **two-step code** (`MFA_OFF`, development only). E-mail is sent to memory, not delivered.
- The demonstration staff account in `bootstrap_demo` carries a real person's name; in the documentation instance that persona was renamed **"Liza Fernandez"** (initials LF in control codes) so no real employee is presented as sample data. All other names are the fictitious ones shipped with the project.
- Some figures show records created during capture to illustrate a procedure: incoming document *2026-0101*, an Incoming Data Sync preview of a 3-row **illustrative workbook** (`SAMPLE-2026-100x`), and e-SIRA document *ESIRA-2026-0001* routed to the Division Chief. All are labelled as samples.
- The two-step setup screenshot (Figure for §10.1.3) shows a QR code belonging to a throw-away demonstration account; it has no value outside that instance.
- Markers are drawn by the script at the position of the actual control found on the page, and the legend is generated from the same definition, so numbers and descriptions cannot disagree.

## 3. Verification performed

1. **Labels and routes** — all 227 URL patterns were enumerated from Django's resolver; the visible headings, buttons, links, form labels, select options and table headings of 73 pages were dumped from the running system and used as the source for every label in the manual.
2. **Permissions** — every page was opened with each of the five roles; the role matrix in §9.2 and the inventory reflect the actual 200/403 results, not assumptions.
3. **Workflow rules** — checked in code where the UI alone could not show them, e.g. who may review (`documents/workflow.py`: LGMED Staff may *mark reviewed*; only Administrators *assign*), that recording the communication sent does not close an incoming document (`incoming/workflow.py`), who may record updates (`IncomingDocument.may_be_updated_by`), when an Administrator is forced into two-step setup (`accounts/views.py`), when a document may be public (`documents/models.py`), upload types and size limits (`*/models.py`), settings ranges (`administration/models.py`), session lifetime (`config/settings.py`).
4. **Rendering** — the PDF was rendered page by page and inspected; the DOCX and PPTX were opened in Microsoft Word and PowerPoint (read-only) and exported to images for inspection. Defects found and fixed during QA: a wrong TOC page for §10.18, legend tables splitting across pages, Word list numbering running on between procedures, header/footer tab alignment, and output size (images now embedded as optimised JPEG copies; the lossless PNGs remain the source).

## 4. Known documentation gaps

| Gap | Why | What is needed |
|---|---|---|
| e-SIRA **signing** (sign dialog, signed result, *Verify signatures*, *Mark as completed*, *Download signed PDF*) | The documentation instance has no PNPKI certificate and no PNPKI trust roots | A test certificate on the documentation instance (`ESIRA_ALLOW_UNTRUSTED_CERTIFICATES=1`, development only), registered and verified, then capture the sign dialog and the signed document |
| Two-step **code entry** page at sign-in and **recovery codes** page | Two-step is switched off on the documentation instance | Capture on an instance with `MFA_OFF` unset, using a demonstration account |
| PPA **file review** page, **Arrange photographs** | No uploaded files/photographs in the demonstration data | Upload a sample file and photographs in a capture step, then capture `/app/programs/documents/<id>/` and the arrangement page |
| Document **Dispose permanently** and **Restore** dialogs | No archived document marked *For disposal*; no disposal authority recorded | Record a disposal authority and archive/mark a sample document in a capture step |
| Data Sync **commit result** and Outgoing **Import Error Report** | Capture stops at the preview so the sample is not imported | Add a commit step for a sample workbook |
| Forms not shown: memorandum, POPS Plan, Ways Forward, reset password, reference-list entry, per-account menu permissions, audit entry detail, e-SIRA audit trail | Described in text from verified field labels; not yet pictured | Add figure entries to `build/figures.py` |
| 404/500 pages and the public **maintenance notice** | Not captured | Add figure entries (maintenance notice: untick *Public website available* on the documentation instance) |
| Public website pages | The manual covers the internal system; the public site is described briefly | Optional separate visitor guide |

## 5. Features requiring confirmation by the office

1. **Top-bar "Search records…" box** — its form submits to the current page (`action="#"`); on module list pages the module's own search box is the documented method. Confirm the intended behaviour of the global box.
2. **"DNS" vs "DMS"** — the interface uses both terms for the document numbering reference (e.g. *DNS number* on Incoming, *DMS number (outgoing)* and *DMS 2026-0005* on Outgoing). The manual follows the screen in each place; the office may wish to standardise.
3. **Browser support** — Chrome and Edge are recommended (screenshots taken in Chrome); Firefox and Safari are stated as usable but were not tested.
4. **Server address** — the manual uses `https://<server>/staff`; insert the production address in §5 once deployed.
5. **Reviewer/approver names** in *Document Control* are left blank for the office to complete.
6. `docs/url-map.md` is slightly out of date (Menu Permissions, Document Files, Data Sync error report, and Roles at `/accounts/roles/`); the manual's Appendix A reflects the current routes.

## 6. Completing the remaining visual documentation

1. Start the documentation instance (see `README.md`).
2. Add the missing figures to `build/figures.py` (one entry each: user, url, steps, markers, caption), and a `{{figure:<id>}}` token where each belongs in `src/`.
3. Run `python capture.py <id-prefix>` for just the new figures, then `python build.py`.
4. The build lists any token without a capture, any unused capture and any marker not found — it should report **0 problems**.
