from django.shortcuts import render
import qrcode
from django.core.files import File
from io import BytesIO
from django.core.mail import send_mail


def generate_qr(ticket):
    qr = qrcode.make(str(ticket.code))
    buffer = BytesIO()
    qr.save(buffer, format='PNG')
    ticket.qr_code.save(f'{ticket.code}.png', File(buffer), save=True)


def send_ticket_email(user, ticket):
    email = EmailMessage(
        subject="Your Event Ticket",
        body=f"Your ticket code: {ticket.code}",
        to=[user.email]
    )

    email.attach_file(ticket.qr_code.path)
    email.send()