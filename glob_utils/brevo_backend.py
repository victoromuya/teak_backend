import base64
from email.utils import getaddresses, parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import sanitize_address
from django.core.exceptions import ImproperlyConfigured


class BrevoEmailBackend(BaseEmailBackend):
    """Send Django EmailMessage objects through Brevo's transactional API."""

    api_url = "https://api.brevo.com/v3/smtp/email"

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, "BREVO_API_KEY", "")
        if not api_key:
            if self.fail_silently:
                return 0
            raise ImproperlyConfigured("BREVO_API_KEY is not configured.")

        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                self._send_message(message, api_key)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent

    def _send_message(self, message, api_key):
        sender_name, sender_email = parseaddr(
            sanitize_address(
                message.from_email or settings.DEFAULT_FROM_EMAIL,
                message.encoding or settings.DEFAULT_CHARSET,
            )
        )
        payload = {
            "sender": {
                "email": sender_email,
                "name": sender_name or getattr(settings, "BREVO_SENDER_NAME", "TickFirst"),
            },
            "to": self._recipients(message.to),
            "subject": str(message.subject),
        }

        html_content = self._html_content(message)
        if html_content is not None:
            payload["htmlContent"] = html_content
        else:
            payload["textContent"] = str(message.body or " ")

        if message.cc:
            payload["cc"] = self._recipients(message.cc)
        if message.bcc:
            payload["bcc"] = self._recipients(message.bcc)
        if message.reply_to:
            reply_name, reply_email = parseaddr(message.reply_to[0])
            payload["replyTo"] = {"email": reply_email}
            if reply_name:
                payload["replyTo"]["name"] = reply_name

        attachments = self._attachments(message)
        if attachments:
            payload["attachment"] = attachments

        response = requests.post(
            self.api_url,
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            json=payload,
            timeout=getattr(settings, "BREVO_API_TIMEOUT", 30),
        )
        response.raise_for_status()

    @staticmethod
    def _recipients(addresses):
        recipients = []
        for name, address in getaddresses(addresses or []):
            recipient = {"email": address}
            if name:
                recipient["name"] = name
            recipients.append(recipient)
        return recipients

    @staticmethod
    def _html_content(message):
        for alternative in message.alternatives:
            content = getattr(alternative, "content", alternative[0])
            mimetype = getattr(alternative, "mimetype", alternative[1])
            if mimetype == "text/html":
                return str(content)
        return None

    @staticmethod
    def _attachments(message):
        attachments = []
        for attachment in message.attachments:
            if hasattr(attachment, "get_payload"):
                content = attachment.get_payload(decode=True)
                filename = attachment.get_filename()
            else:
                filename = getattr(attachment, "filename", attachment[0])
                content = getattr(attachment, "content", attachment[1])

            if not filename or content is None:
                continue
            if isinstance(content, str):
                content = content.encode()
            attachments.append({
                "name": filename,
                "content": base64.b64encode(content).decode("ascii"),
            })
        return attachments
