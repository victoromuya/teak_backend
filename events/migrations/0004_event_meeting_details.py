from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("events", "0003_event_featured_and_soft_delete")]

    operations = [
        migrations.AddField(
            model_name="event", name="meeting_platform",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="event", name="meeting_link",
            field=models.URLField(blank=True, max_length=1000, null=True),
        ),
    ]
