from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('accounts', '0009_emailotp_ticket_access'), ('orders', '0007_failed_incomplete_orders')]
    operations = [migrations.AddField(model_name='order', name='guest_otp', field=models.OneToOneField(
        to='accounts.emailotp', null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
    ))]
