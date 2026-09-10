"""
Bring the existing office hours row in line with the model default.

`AlterField` only restates the default for *future* rows; the singleton was
created back in 0002 and has held the original string ever since. Changing
the value an officer actually sees takes a data migration like this one.

The update is conditional: if the hours have been edited on the Public
Website page, that edit is the more current fact and is left alone.
"""

from django.db import migrations

# Historical models carry no custom attributes, so `PublicSiteContent.CACHE_KEY`
# is not reachable from here and the key is repeated rather than imported.
CACHE_KEY = "lgmed:public-site-content"

OLD = "Monday to Friday, 8:00 AM - 5:00 PM"
NEW = "Monday to Thursday, 7:00 AM - 7:00 PM"


def _set_hours(apps, schema_editor, previous, current):
    PublicSiteContent = apps.get_model("administration", "PublicSiteContent")
    PublicSiteContent.objects.filter(pk=1, office_hours=previous).update(
        office_hours=current
    )

    from django.core.cache import cache

    cache.delete(CACHE_KEY)


def forwards(apps, schema_editor):
    _set_hours(apps, schema_editor, OLD, NEW)


def backwards(apps, schema_editor):
    _set_hours(apps, schema_editor, NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("administration", "0005_alter_publicsitecontent_office_hours"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
