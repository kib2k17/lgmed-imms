# MySQL cannot reliably index a unique VARCHAR longer than 255 characters
# (mysql.W003), so every PPA slug is capped there.

from django.db import migrations, models

SLUG_FIELD = dict(
    blank=True,
    help_text="Used in the public web address. Never a database number.",
    max_length=255,
    unique=True,
)


class Migration(migrations.Migration):

    dependencies = [
        ("programs", "0008_activity_about_heading_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="activity",
            name="slug",
            field=models.SlugField(**SLUG_FIELD),
        ),
        migrations.AlterField(
            model_name="program",
            name="slug",
            field=models.SlugField(**SLUG_FIELD),
        ),
        migrations.AlterField(
            model_name="project",
            name="slug",
            field=models.SlugField(**SLUG_FIELD),
        ),
        migrations.AlterField(
            model_name="subproject",
            name="slug",
            field=models.SlugField(**SLUG_FIELD),
        ),
    ]
