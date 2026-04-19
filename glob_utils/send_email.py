import smtplib
from email.message import EmailMessage
from django.conf import settings

def send_email(subject, body, to_email):
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_HOST_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL(
            settings.EMAIL_HOST,
            settings.EMAIL_PORT,
            timeout=settings.EMAIL_TIMEOUT,
        ) as server:
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(msg)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error: {e}")
