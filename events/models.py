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



    EVENT_TYPE = (
        ("ONLINE", "ONLINE"),
        ("IN_PERSON", "IN_PERSON"),
    )

    title = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True, null=True)  # Music, Sports, Tech, etc.
    type = models.CharField(max_length=100, choices=EVENT_TYPE, blank=True, null=True)  # Online or In-Person
    description = models.TextField()
    address = models.CharField(max_length=255, blank=True, null=True)
    state=models.CharField(max_length=100,  blank=True, null=True)
    city=models.CharField(max_length=100, blank=True, null=True)
    country=models.CharField(max_length=100, blank=True, null=True)
    paid_event = models.BooleanField(default=False)  
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    attendees_age_range = models.CharField(max_length=50, blank=True, null=True)  # e.g., "18-35"
    banner = models.ImageField(upload_to="events/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'Events'


class TicketType(models.Model):
    event = models.ForeignKey(
        Event,
        related_name="ticket_types",
        on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)  # Regular, VIP, Early Bird
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)  # Free events can have null price
    sales_expiry_date = models.DateTimeField(blank=True, null=True)
    quantity = models.PositiveIntegerField(default=100)
    remaining = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'TicketTypes'