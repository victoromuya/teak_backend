# events/models.py

from django.db import models
from django.conf import settings
from django.utils import timezone


class Event(models.Model):
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="events"
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    location = models.CharField(max_length=255)
    date = models.DateTimeField()
    banner = models.ImageField(upload_to="events/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TicketType(models.Model):
    event = models.ForeignKey(
        Event,
        related_name="ticket_types",
        on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)  # Regular, VIP, Early Bird
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=100)
    remaining = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(default=timezone.now)