"""
Bring LGMED codes already issued by the system into the current rules.

- Codes are written without parentheses round the initials:
  "LGMED-13 - (JD) - 2026-09-29-0001" becomes "LGMED-13 - JD - 2026-09-29-0001".
  Only codes the system issued (on incoming documents) are rewritten; the
  spreadsheet register's historical rows are left as the office wrote them.
- A document already acknowledged moves to Outgoing Monitoring, as it would
  have if it were acknowledged today.
"""

import re

from django.db import migrations

_PARENTHESISED = re.compile(r" - \(([^)]*)\) - ")


def forward(apps, schema_editor):
    IncomingDocument = apps.get_model("incoming", "IncomingDocument")
    OutgoingDocument = apps.get_model("outgoing", "OutgoingDocument")

    for document in IncomingDocument.objects.exclude(lgmed_code__isnull=True):
        old = document.lgmed_code
        new = _PARENTHESISED.sub(r" - \1 - ", old)
        if new != old:
            document.lgmed_code = new
            document.save(update_fields=["lgmed_code"])
            # A reply already filed under the old code keeps up with it.
            OutgoingDocument.objects.filter(control_code=old).update(control_code=new)

        outgoing = OutgoingDocument.objects.filter(control_code=new).first()
        if outgoing is None and document.acknowledged_at is None:
            continue
        if outgoing is None:
            outgoing = OutgoingDocument(
                control_code=new,
                subject=document.subject,
                created_by_id=document.assigned_to_id,
            )
        outgoing.incoming_id = document.pk
        outgoing.incoming_reference = outgoing.incoming_reference or document.docket_number
        outgoing.save()


class Migration(migrations.Migration):
    dependencies = [
        ("incoming", "0004_lgmed_code"),
        ("outgoing", "0003_incoming_link"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
