"""
Give the activities that already exist an owner and a visibility.

Both new fields have defaults that are right for a record created from now on
and wrong for one created before ownership existed: a division-wide calendar
entry encoded last month is not private to whoever happened to type it in, and
making it so would empty the calendar for everybody else on the morning this
migration ran. Existing rows are therefore made office-wide, and owned by the
person who encoded them - the closest thing the old records hold to an owner.
"""

from django.db import migrations
from django.db.models import F, OuterRef, Subquery


def adopt_existing_activities(apps, schema_editor):
    CalendarActivity = apps.get_model("activities", "CalendarActivity")
    User = apps.get_model("accounts", "User")

    CalendarActivity.objects.filter(
        owner__isnull=True, created_by__isnull=False
    ).update(owner_id=F("created_by_id"))

    CalendarActivity.objects.update(visibility="ORGANIZATION")

    CalendarActivity.objects.filter(
        section__isnull=True, owner__isnull=False
    ).update(
        section_id=Subquery(
            User.objects.filter(pk=OuterRef("owner_id")).values("section_id")[:1]
        )
    )


def unadopt(apps, schema_editor):
    """
    Reversing puts the rows back to the field defaults.

    The columns are dropped by the schema migration this one depends on, so
    nothing is lost - but leaving the reverse unimplemented would make the
    migration irreversible for no reason.
    """
    CalendarActivity = apps.get_model("activities", "CalendarActivity")
    CalendarActivity.objects.update(owner=None, section=None, visibility="PRIVATE")


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0002_calendaractivity_assigned_to_and_more"),
        ("accounts", "0002_section_user_section"),
    ]

    operations = [
        migrations.RunPython(adopt_existing_activities, unadopt),
    ]
