from django.db import migrations, models


def mark_expired_orders_failed(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.using(schema_editor.connection.alias).filter(status="expired").update(status="failed")


class Migration(migrations.Migration):
    dependencies = [("orders", "0006_order_processing_fee")]

    operations = [
        migrations.RunPython(mark_expired_orders_failed, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed")],
                default="pending",
                max_length=20,
            ),
        ),
    ]
