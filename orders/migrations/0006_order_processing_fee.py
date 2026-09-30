from decimal import Decimal

from django.db import migrations, models


def preserve_existing_payment_amounts(apps, schema_editor):
    # Already-initialized and paid orders retain their original charge.
    Order = apps.get_model("orders", "Order")
    Order.objects.using(schema_editor.connection.alias).update(payment_amount=models.F("total_amount"))


class Migration(migrations.Migration):
    dependencies = [("orders", "0005_order_revenue_split")]

    operations = [
        migrations.AddField(
            model_name="order", name="processing_fee",
            field=models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), editable=False),
        ),
        migrations.AddField(
            model_name="order", name="payment_amount",
            field=models.DecimalField(max_digits=12, decimal_places=2, null=True, editable=False),
        ),
        migrations.RunPython(preserve_existing_payment_amounts, migrations.RunPython.noop),
    ]
