"""
Build the throw-away documentation instance the manual's screenshots come from.

Run with the project's own interpreter, from the project root, while no
documentation server is running (Windows will not delete an open database):

    $env:DJANGO_SETTINGS_MODULE = "docs_settings"
    $env:PYTHONPATH = "docs\\manual\\build"
    $env:PYTHONUTF8 = "1"
    venv\\Scripts\\python docs\\manual\\build\\setup_instance.py

It deletes and recreates LGDOCS_WORKDIR (default C:\\lgdt) data only - the
SQLite file, media and protected folders - then loads the project's own
reference and demonstration data. Nothing in the working copy's database,
media/ or protected/ is touched.
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docs_settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

# The demonstration staff account carries a real person's name in
# bootstrap_demo. The manual should not present a real employee as a sample,
# so this instance renames that persona; every other account is fictional.
PERSONA = {"username": "lgmed.staff", "first": "Liza", "last": "Fernandez",
           "old_full": "Karl Kevin Bacon", "old_last": "Bacon",
           "old_initials": "KKB", "new_initials": "LF"}


def reset_workdir():
    work = Path(settings.WORKDIR)
    db = Path(settings.DATABASES["default"]["NAME"])
    connection.close()
    if db.exists():
        db.unlink()
    for folder in (settings.MEDIA_ROOT, settings.PROTECTED_MEDIA_ROOT):
        shutil.rmtree(folder, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)


def seed():
    call_command("migrate", verbosity=0)
    call_command("seed_lgus")
    call_command("bootstrap_demo")
    call_command("seed_records")


def rename_persona():
    from accounts.models import User

    User.objects.filter(username=PERSONA["username"]).update(
        first_name=PERSONA["first"], last_name=PERSONA["last"])
    new_full = f"{PERSONA['first']} {PERSONA['last']}"
    pairs = ((PERSONA["old_full"], new_full), (PERSONA["old_last"], PERSONA["last"]),
             (PERSONA["old_initials"], PERSONA["new_initials"]))
    changed = 0
    with connection.cursor() as cur:
        tables = connection.introspection.table_names(cur)
        for table in tables:
            for col in connection.introspection.get_table_description(cur, table):
                if col.type_code not in ("text", "varchar") and "char" not in str(col.type_code).lower():
                    continue
                for old, new in pairs:
                    cur.execute(
                        f'UPDATE "{table}" SET "{col.name}" = REPLACE("{col.name}", %s, %s) '
                        f'WHERE "{col.name}" LIKE %s', [old, new, f"%{old}%"])
                    changed += cur.rowcount
    print(f"Persona renamed; {changed} stored text value(s) updated.")


def tiny_pdf(lines):
    """A valid one-page PDF with plain text - no PDF library needed."""
    text = "BT /F1 13 Tf 72 760 Td 18 TL " + " ".join(
        "(%s) '" % s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for s in lines
    ) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
    ]
    out, offsets = "%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def sample_files():
    from openpyxl import Workbook
    from PIL import Image, ImageDraw

    samples = Path(settings.WORKDIR) / "samples"
    samples.mkdir(exist_ok=True)
    (samples / "sample-memorandum.pdf").write_bytes(tiny_pdf([
        "SAMPLE DOCUMENT - FOR THE USER MANUAL ONLY",
        "",
        "MEMORANDUM",
        "FOR: The Division Chief, LGMED",
        "SUBJECT: Request for validation of submitted documents (illustrative)",
        "",
        "This file was generated to demonstrate uploading in LGMED-iMMS.",
        "It contains no real records.",
    ]))
    img = Image.new("RGB", (1200, 800), (226, 232, 240))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 60, 1140, 740], outline=(30, 64, 175), width=8)
    d.text((100, 380), "SAMPLE PHOTOGRAPH - USER MANUAL", fill=(30, 41, 59))
    img.save(samples / "sample-photo.jpg", quality=85)

    wb = Workbook()
    ws = wb.active
    ws.title = "October 2026"
    ws.append(["Date", "HUC/Province", "Docket Number", "Subject", "Assigned Focal/Remarks"])
    ws.append(["2026-10-01", "Agusan del Norte", "SAMPLE-2026-1001",
               "Request for technical assistance (sample row)", "For the Chief's review"])
    ws.append(["2026-10-02", "Surigao del Sur", "SAMPLE-2026-1002",
               "Submission of monitoring report (sample row)", "Encoded for the manual"])
    ws.append(["", "Dinagat Islands", "SAMPLE-2026-1003",
               "Invitation to an orientation (sample row)", "Date carried from the row above"])
    wb.save(samples / "sample-incoming-register.xlsx")
    print(f"Sample files written to {samples}")


if __name__ == "__main__":
    if not settings.DEBUG or "sqlite" not in settings.DATABASES["default"]["ENGINE"]:
        sys.exit("Refusing: this script only builds the SQLite documentation instance.")
    reset_workdir()
    seed()
    rename_persona()
    call_command("refresh_notifications")
    sample_files()
    print("Documentation instance ready.")
