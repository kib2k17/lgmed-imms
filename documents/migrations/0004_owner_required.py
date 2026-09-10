"""
Make a document's owner compulsory, now that every existing row has one.

Written by hand rather than generated, because the generator can only offer to
invent a default for the rows it is about to break - and the right answer was
never a default. It was the backfill in 0003, which gave each document the
account that encoded it, or an administrator where the old repository had not
recorded one. This migration only closes the door behind it.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("documents", "0003_backfill_document_management"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="owner",
            field=models.ForeignKey(
                help_text=(
                    "The person answerable for this document. Defaults to "
                    "whoever registers it."
                ),
                on_delete=django.db.models.deletion.PROTECT,
                related_name="documents_owned",
                to=settings.AUTH_USER_MODEL,
                verbose_name="owner / responsible personnel",
            ),
        ),
    ]
