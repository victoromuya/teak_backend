from decimal import Decimal
from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("events", "0003_event_featured_and_soft_delete"),
        ("orders", "0003_protect_order_history"),
    ]

    operations = [
        migrations.CreateModel(
            name="WithdrawalRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("gross_revenue", models.DecimalField(decimal_places=2, max_digits=12)),
                ("fee_percentage", models.DecimalField(decimal_places=2, max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal("0")), django.core.validators.MaxValueValidator(Decimal("100"))])),
                ("fee_amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("contact", models.CharField(max_length=100)),
                ("account_number", models.CharField(max_length=30)),
                ("bank_name", models.CharField(max_length=120)),
                ("account_name", models.CharField(max_length=160)),
                ("email", models.EmailField(max_length=254)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("rejected", "Rejected")], default="pending", max_length=20)),
                ("admin_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("completed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="completed_withdrawals", to=settings.AUTH_USER_MODEL)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="withdrawal_requests", to="events.event")),
                ("organizer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="withdrawal_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "WithdrawalRequests", "ordering": ["-created_at"]},
        ),
    ]
