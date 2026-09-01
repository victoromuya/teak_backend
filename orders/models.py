import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from events.models import Event, TicketType
from datetime import timezone, timedelta


class Order(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("expired", "Expired"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, default=1)
    reference = models.CharField(max_length=100, unique=True, default="aaa")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    def is_expired(self):
        return (
            self.status == "pending" and
            timezone.now() > self.created_at + timedelta(minutes=10)
        )

    class Meta:
        db_table = 'Orders'

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    ticket_type = models.ForeignKey(TicketType, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2, default=100.0)

    class Meta:
        db_table = 'OrderItems'



# orders/models.py

from django.conf import settings

class Ticket(models.Model):

    order = models.ForeignKey(Order, on_delete=models.CASCADE)

    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.CASCADE,
        default=1,
    )

    ticket_code = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True
    )

    qr_image = models.ImageField(upload_to="ticketQR/")

    is_used = models.BooleanField(default=False)

    scanned_at = models.DateTimeField(
        null=True,
        blank=True
    )

    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scanned_tickets"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "Tickets"


class WithdrawalRequest(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("rejected", "Rejected"),
    )

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="withdrawal_requests",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        related_name="withdrawal_requests",
    )
    gross_revenue = models.DecimalField(max_digits=12, decimal_places=2)
    fee_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    contact = models.CharField(max_length=100)
    account_number = models.CharField(max_length=30)
    bank_name = models.CharField(max_length=120)
    account_name = models.CharField(max_length=160)
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="completed_withdrawals",
    )

    class Meta:
        db_table = "WithdrawalRequests"
        ordering = ["-created_at"]
