from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from events.models import Event
from .models import Order


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
        {"order": order, "event": event, "updated": updated},
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
