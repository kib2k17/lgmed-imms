# LGMED-iMMS System User Manual — sources and build

| File | What it is |
|---|---|
| `system-user-manual.pdf` | The publication-ready manual (A4, bookmarks, clickable contents) |
| `system-user-manual.docx` | Editable Word version (the table of contents refreshes when opened) |
| `system-user-manual.pptx` | Slide version — one slide per annotated figure; imports into Canva (*Create a design › Import file*) or PowerPoint |
| `system-user-manual.md` / `.html` | The complete manual as Markdown and as a single web page |
| `module-inventory.md` | Every module: purpose, roles, routes, procedures, screenshots, gaps |
| `documentation-report.md` | What was verified, how screenshots were made, known gaps |
| `src/*.md` | **The text — edit these.** One file per chapter, in file-name order |
| `assets/<module>/*.png` | Annotated screenshots used in the manual |
| `assets/diagrams/*.png` | Workflow diagrams (generated) |
| `assets/figures.json` | Caption, role, page and legend of every screenshot (generated) |
| `build/figures.py` | **The screenshot definitions — edit these.** Who signs in, which page, what is done, which controls are marked |
| `build/capture.py` | Takes and annotates the screenshots from the running system |
| `build/diagrams.py` | The workflow diagrams, as data |
| `build/build.py`, `build/manual.css` | Assembles every output format |
| `build/setup_instance.py`, `build/docs_settings.py` | The throw-away documentation instance the screenshots come from |

Do not edit the generated `system-user-manual.*` files — they are overwritten by the build.

## Writing

Chapters are ordinary Markdown with three tokens:

- `{{figure:incoming-new}}` — inserts the screenshot, its numbered caption and its legend;
- `{{diagram:incoming}}` — inserts a workflow diagram;
- `{{ref:incoming-new}}` — the figure's number (write `Figure {{ref:incoming-new}}`).

Figures are numbered automatically in order of appearance. Callouts are block quotes that start with `**NOTE:**`, `**TIP:**`, `**IMPORTANT:**` or `**WARNING:**`. Procedures are `### Procedure x.y: Title` followed by **Purpose**, **Who can do this**, **Steps**, **Expected Result**, **Visual Reference** and **Important Notes**.

## Regenerating

Tools (once, in any Python 3.12+ outside the project venv; a short path such as `C:\lgdt` avoids Windows path-length errors):

```powershell
py -m venv C:\lgdt\v
C:\lgdt\v\Scripts\pip install -r docs\manual\build\requirements.txt
```

Google Chrome must be installed (the scripts drive it; no browser download is needed).

1. **Build the documentation instance** — a fresh SQLite database and media folder under `C:\lgdt` with demonstration data only. Never point this at the office database.

   ```powershell
   $env:DJANGO_SETTINGS_MODULE = "docs_settings"
   $env:PYTHONPATH = "docs\manual\build"
   $env:PYTHONUTF8 = "1"
   venv\Scripts\python docs\manual\build\setup_instance.py
   venv\Scripts\python manage.py runserver 127.0.0.1:8765 --noreload
   ```

2. **Capture** (second terminal; the server must be running):

   ```powershell
   cd docs\manual\build
   C:\lgdt\v\Scripts\python capture.py                 # all figures
   C:\lgdt\v\Scripts\python capture.py incoming- esira  # only ids starting with these
   ```

   Some figures depend on the one before (for example `incoming-new` saves the record that `incoming-recorded` shows), so recapture such a group together, and rebuild the instance (step 1) before a full recapture.

3. **Build** every format:

   ```powershell
   C:\lgdt\v\Scripts\python build.py            # md html pdf docx pptx
   C:\lgdt\v\Scripts\python build.py pdf docx   # only some
   ```

   The build prints any token without a screenshot, unused screenshot or marker not found. It should end with `0 problem(s)`.

When the system changes: update the affected `src/` chapter, adjust `build/figures.py` if a label or page moved, recapture that module, rebuild, and add a row to `HISTORY` in `build/build.py` (and raise `MANUAL_VERSION`).
