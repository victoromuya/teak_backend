from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

def send_email(
    subject,
    body,
    to_email,
    *,
    heading=None,
    action_label=None,
    action_url=None,
    reply_to=None,
):
    """Send a branded multipart email through Django's Brevo backend."""
    recipients = [to_email] if isinstance(to_email, str) else list(to_email)
    html = render_to_string("emails/notification.html", {
        "preheader": subject,
        "heading": heading or subject,
        "body": body,
        "action_label": action_label,
        "action_url": action_url,
        "frontend_url": settings.FRONTEND_URL.rstrip("/"),
    })

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
        reply_to=reply_to or [],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)
