# MySQL cannot reliably index a unique VARCHAR longer than 255 characters
# (mysql.W003), so the slug is capped there.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("announcements", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="announcement",
            name="slug",
            field=models.SlugField(blank=True, help_text="Left blank, this is generated from the headline.", max_length=255, unique=True),
        ),
    ]
