from decimal import Decimal, InvalidOperation
from io import BytesIO

import qrcode
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from events.models import TicketType

from .models import Order, Ticket


class PaymentFinalizationError(Exception):
    pass


class OrderNotFoundError(PaymentFinalizationError):
    pass


class InvalidPaymentError(PaymentFinalizationError):
    pass


class InsufficientInventoryError(PaymentFinalizationError):
    pass


def finalize_paystack_payment(reference, payment_data):
    """Validate and fulfill a successful Paystack charge exactly once."""
    if not reference or not isinstance(payment_data, dict):
        raise InvalidPaymentError("Invalid payment data")
    if payment_data.get("reference") != reference:
        raise InvalidPaymentError("Payment reference mismatch")
    if payment_data.get("status") != "success":
        raise InvalidPaymentError("Payment not successful")

    currency = payment_data.get("currency")
    if not isinstance(currency, str) or currency.upper() != "NGN":
        raise InvalidPaymentError("Payment currency mismatch")

    with transaction.atomic():
        try:
            order = (
                Order.objects.select_for_update()
                .select_related("user", "event")
                .get(reference=reference)
            )
        except Order.DoesNotExist as exc:
            raise OrderNotFoundError("Order not found") from exc

        try:
            paid_amount = int(payment_data["amount"])
            expected_amount = int(Decimal(order.total_amount) * Decimal("100"))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise InvalidPaymentError("Invalid payment amount") from exc
        if paid_amount != expected_amount:
            raise InvalidPaymentError("Payment amount mismatch")

        # Locking the order makes callbacks and duplicate webhooks idempotent.
        if order.status == "paid":
            tickets = list(
                order.ticket_set.select_related("ticket_type").order_by("id")
            )
            return order, tickets, False

        order_items = list(order.items.select_related("ticket_type").all())
        type_ids = {item.ticket_type_id for item in order_items}
        ticket_types = {
            ticket_type.id: ticket_type
            for ticket_type in TicketType.objects.select_for_update().filter(
                id__in=type_ids
            )
        }

        for item in order_items:
            ticket_type = ticket_types[item.ticket_type_id]
            if ticket_type.remaining < item.quantity:
                raise InsufficientInventoryError(
                    f"Insufficient tickets for {ticket_type.name}"
                )

        for item in order_items:
            ticket_type = ticket_types[item.ticket_type_id]
            ticket_type.remaining -= item.quantity
            ticket_type.save(update_fields=["remaining"])

        tickets = [] if order.event.type == "ONLINE" else _generate_tickets(order, order_items)
        order.status = "paid"
        order.verified_at = timezone.now()
        order.save(update_fields=["status", "verified_at"])
        transaction.on_commit(lambda: _send_ticket_email(order.pk))

    return order, tickets, True


def _generate_tickets(order, order_items):
    tickets = []
    for item in order_items:
        for _ in range(item.quantity):
            ticket = Ticket.objects.create(
                order=order,
                ticket_type=item.ticket_type,
            )
            qr = qrcode.make(str(ticket.ticket_code))
            buffer = BytesIO()
            qr.save(buffer, format="PNG")
            buffer.seek(0)
            ticket.qr_image.save(
                f"{ticket.ticket_code}.png",
                File(buffer),
                save=True,
            )
            tickets.append(ticket)
    return tickets


def _send_ticket_email(order_id):
    # Import lazily so the existing email renderer remains the single template.
    from .notifications import send_online_event_email
    from .views import send_ticket_email

    try:
        order = Order.objects.select_related("event", "user").get(pk=order_id)
        if order.event.type == "ONLINE":
            send_online_event_email(order)
        else:
            send_ticket_email(order)
    except Exception:
        # Fulfillment must not be rolled back or retried because email failed.
        pass
