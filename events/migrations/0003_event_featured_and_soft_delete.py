from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0002_create_free_ticket_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="is_featured",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="event",
            name="is_deleted",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
