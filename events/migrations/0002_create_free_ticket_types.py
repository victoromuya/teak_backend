from django.db import migrations


def create_free_ticket_types(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    TicketType = apps.get_model("events", "TicketType")

    for event in Event.objects.filter(paid_event=False).iterator():
        if TicketType.objects.filter(event=event, price=0).exists():
            continue
        TicketType.objects.create(
            event=event,
            name="Free Entry",
            price=0,
            quantity=100,
            remaining=100,
        )


class Migration(migrations.Migration):
    dependencies = [("events", "0001_initial")]

    operations = [
        migrations.RunPython(create_free_ticket_types, migrations.RunPython.noop),
    ]
