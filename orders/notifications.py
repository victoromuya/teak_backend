import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from events.models import Event
from glob_utils.send_email import send_email
from .models import Order


logger = logging.getLogger(__name__)


def notify_organizer_of_purchase(order_id):
    """Send one sale notice after a newly completed order commits."""
    try:
        order = Order.objects.select_related("event__organizer", "user").get(pk=order_id)
        organizer_email = order.event.organizer.email
        if not organizer_email:
            return

        items = list(order.items.select_related("ticket_type"))
        ticket_count = sum(item.quantity for item in items)
        ticket_lines = "\n".join(
            f"- {item.ticket_type.name}: {item.quantity}"
            for item in items
        )
        order_url = f"{settings.FRONTEND_URL.rstrip('/')}/organizer/orders/{order.pk}"
        send_email(
            subject=f"Ticket purchase for {order.event.title}",
            heading="A ticket purchase is confirmed",
            body=(
                f"A customer has booked {ticket_count} ticket(s) for {order.event.title}.\n\n"
                f"Buyer: {order.user.email}\n"
                f"Order reference: {order.reference}\n"
                f"Tickets:\n{ticket_lines}\n"
                f"Order total: NGN {order.total_amount:,.2f}"
            ),
            to_email=organizer_email,
            action_label="View order",
            action_url=order_url,
        )
    except Exception:
        # A mail provider failure must not reverse a confirmed booking.
        logger.exception("Organizer purchase email failed for order %s", order_id)


def send_online_event_email(order, updated=False):
    event = order.event
    subject = (
        f"Updated event link: {event.title}"
        if updated else f"Your online event link: {event.title}"
    )
    status_text = "has been updated" if updated else "is below"
    name = order.user.get_full_name() or order.user.email
    text = (
        f"Hi {name},\n\nThe private link for {event.title} {status_text}.\n"
        f"Platform: {event.meeting_platform}\nEvent link: {event.meeting_link}\n\n"
        "This link is private and must not be shared with anyone."
    )
    html = render_to_string(
        "emails/online_event_link.html",
        {"order": order, "event": event, "updated": updated, "frontend_url": settings.FRONTEND_URL.rstrip("/")},
    )
    message = EmailMultiAlternatives(
        subject, text, settings.DEFAULT_FROM_EMAIL, [order.user.email]
    )
    message.attach_alternative(html, "text/html")
    message.send(fail_silently=False)


def email_online_event_attendees(event_id, updated=False):
    event = Event.objects.get(pk=event_id, type="ONLINE")
    orders = Order.objects.filter(event=event, status="paid").select_related(
        "user", "event"
    ).order_by("created_at")
    seen = set()
    for order in orders:
        if order.user_id in seen:
            continue
        seen.add(order.user_id)
        try:
            send_online_event_email(order, updated=updated)
        except Exception:
            # Saving a valid link must not fail because the mail provider is down.
            continue
