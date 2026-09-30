from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models
from django.conf import settings


def backfill_revenue(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    database = schema_editor.connection.alias
    organizer_rate = (Decimal("100") - Decimal(str(settings.TICKET_PLATFORM_FEE_PERCENTAGE))) / Decimal("100")
    for order in Order.objects.using(database).filter(status="paid").prefetch_related("items").iterator(chunk_size=500):
        items = list(order.items.all())
        if items and sum(item.price * item.quantity for item in items) == order.total_amount:
            organizer = sum(
                (item.price * organizer_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                * item.quantity for item in items
            )
        else:
            organizer = (order.total_amount * organizer_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        Order.objects.using(database).filter(pk=order.pk).update(
            organizer_revenue=organizer,
            platform_revenue=order.total_amount - organizer,
        )


class Migration(migrations.Migration):
    dependencies = [("orders", "0004_withdrawalrequest")]

    operations = [
        migrations.AddField(
            model_name="order", name="organizer_revenue",
            field=models.DecimalField(max_digits=12, decimal_places=2, null=True, editable=False),
        ),
        migrations.AddField(
            model_name="order", name="platform_revenue",
            field=models.DecimalField(max_digits=12, decimal_places=2, null=True, editable=False),
        ),
        migrations.RunPython(backfill_revenue, migrations.RunPython.noop),
    ]
