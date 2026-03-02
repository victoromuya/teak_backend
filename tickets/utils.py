# tickets/utils.py

import uuid
import qrcode
from io import BytesIO
from django.core.files import File
from .models import Ticket


def create_tickets(order):
    for item in order.items.all():
        for _ in range(item.quantity):

            ticket = Ticket.objects.create(
                order=order,
                code=uuid.uuid4()
            )

            generate_qr(ticket)
            send_ticket_email(order.user, ticket)


def generate_qr(ticket):
    qr = qrcode.make(str(ticket.code))
    buffer = BytesIO()
    qr.save(buffer, format='PNG')
    ticket.qr_code.save(f"{ticket.code}.png", File(buffer), save=True)