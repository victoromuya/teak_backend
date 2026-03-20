import uuid
from django.db import models
from django.conf import settings
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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, default=1)
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


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    ticket_type = models.ForeignKey(TicketType, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2, default=100.0)



class Ticket(models.Model):

    order = models.ForeignKey(Order, on_delete=models.CASCADE)

    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.CASCADE,
        default=1
    )

    ticket_code = models.UUIDField(default=uuid.uuid4,editable=False,unique=True,db_index=True)
    qr_image = models.ImageField(upload_to="ticketQR/")
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)