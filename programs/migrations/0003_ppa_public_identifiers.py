"""
Give the programmes that already existed a public identifier, and decide what
the public may still see of them.

Two jobs, both of them one-off.

**Slugs and tokens.** The rebuilt module addresses records publicly by slug
rather than by database number, so every row that predates the rebuild needs
one. They are filled here, before the unique constraints are applied in the
next migration.

**Publication status.** Every record created from now on starts as a draft and
reaches the public website only through review and approval. Applying that to
the rows that already exist would be wrong in the other direction, though: the
programmes the old module listed as Active or Completed were *already on the
public website* the moment this migration runs, and silently blanking the
public programme page is not a security improvement, it is an outage.

So the migration preserves the disclosure that exists rather than widening or
narrowing it: exactly the programmes the old public view selected are marked
Published, and everything else is left as a draft. No documents are affected -
the old module had none.
"""

import uuid

from django.db import migrations
from django.utils.text import slugify

# What `core.views.public_programs` listed before this rebuild.
PREVIOUSLY_PUBLIC = ("ACTIVE", "COMPLETED")


def fill_identifiers(apps, schema_editor):
    Program = apps.get_model("programs", "Program")

    taken = set()
    for program in Program.objects.all().order_by("pk"):
        base = slugify(program.title)[:240] or f"program-{program.pk}"
        candidate, suffix = base, 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        taken.add(candidate)

        program.slug = candidate
        program.public_token = uuid.uuid4()
        program.publication_status = (
            "PUBLISHED" if program.status in PREVIOUSLY_PUBLIC else "DRAFT"
        )
        program.save(update_fields=["slug", "public_token", "publication_status"])


def clear_identifiers(apps, schema_editor):
    """Reversing drops the slugs; the titles they were built from remain."""
    Program = apps.get_model("programs", "Program")
    Program.objects.update(slug="", publication_status="DRAFT")


class Migration(migrations.Migration):

    dependencies = [
        ("programs", "0002_activity_project_subproject_supportingdocument_and_more"),
    ]

    operations = [
        migrations.RunPython(fill_identifiers, clear_identifiers),
    ]
