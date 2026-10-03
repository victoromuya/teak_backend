from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("events", "0004_event_meeting_details")]

    operations = [
        migrations.AddField(
            model_name="tickettype",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
