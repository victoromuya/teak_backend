import base64
from unittest.mock import patch

from django.core.mail import EmailMultiAlternatives, send_mail
from django.test import SimpleTestCase, override_settings


@override_settings(
    EMAIL_BACKEND="glob_utils.brevo_backend.BrevoEmailBackend",
    BREVO_API_KEY="test-api-key",
    DEFAULT_FROM_EMAIL="TickFirst <hello@tickfirst.net>",
)
class BrevoEmailBackendTests(SimpleTestCase):
    @patch("glob_utils.brevo_backend.requests.post")
    def test_sends_plain_email_with_configured_sender(self, post):
        post.return_value.raise_for_status.return_value = None

        sent = send_mail("Welcome", "Hello", None, ["buyer@example.com"])

        self.assertEqual(sent, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["sender"], {
            "email": "hello@tickfirst.net",
            "name": "TickFirst",
        })
        self.assertEqual(payload["to"], [{"email": "buyer@example.com"}])
        self.assertEqual(payload["textContent"], "Hello")
        self.assertEqual(post.call_args.kwargs["headers"]["api-key"], "test-api-key")

    @patch("glob_utils.brevo_backend.requests.post")
    def test_sends_html_reply_to_and_attachment(self, post):
        post.return_value.raise_for_status.return_value = None
        message = EmailMultiAlternatives(
            subject="Your tickets",
            body="Ticket attached",
            to=["Buyer <buyer@example.com>"],
            reply_to=["support@example.com"],
        )
        message.attach_alternative("<p>Ticket attached</p>", "text/html")
        message.attach("ticket.png", b"png-data", "image/png")

        sent = message.send()

        self.assertEqual(sent, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["htmlContent"], "<p>Ticket attached</p>")
        self.assertEqual(payload["replyTo"], {"email": "support@example.com"})
        self.assertEqual(payload["attachment"], [{
            "name": "ticket.png",
            "content": base64.b64encode(b"png-data").decode("ascii"),
        }])
