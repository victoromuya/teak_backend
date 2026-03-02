# tickets/models.py

from django.db import models
import uuid
from orders.models import Order

class Ticket(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    code = models.UUIDField(default=uuid.uuid4, unique=True)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True)
    used = models.BooleanField(default=False)