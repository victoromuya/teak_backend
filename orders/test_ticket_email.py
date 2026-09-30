from html import unescape
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse
import re

from django.core import mail
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from .views import send_ticket_email


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TicketEmailTests(SimpleTestCase):
    def make_order(self, **event_changes):
        event = dict(title="Music & Friends", type="IN_PERSON", address="12 King & Queen Road",
                     city="Lagos", state="Lagos State", country="Nigeria", start_date=None, start_time=None)
        event.update(event_changes)
        ticket = SimpleNamespace(ticket_code="ticket-123", ticket_type=SimpleNamespace(name="General entry"),
                                 qr_image=Mock(read=Mock(return_value=b"ticket-image")))
        tickets = Mock()
        tickets.all.return_value = [ticket]
        # The sender uses the queryset's no-argument count().
        class Tickets(list):
            def count(self):
                return len(self)
        tickets.all.return_value = Tickets([ticket])
        return SimpleNamespace(event=SimpleNamespace(**event), reference="order-123", ticket_set=tickets,
                               user=SimpleNamespace(email="buyer@example.com"))

    def test_maps_destination_and_attachment_are_delivered(self):
        send_ticket_email(self.make_order())
        message = mail.outbox[-1]
        html = message.alternatives[0].content
        url = unescape(re.search(r'href="(https://www.google.com/maps/dir/[^\"]+)"', html).group(1))
        self.assertEqual(parse_qs(urlparse(url).query), {
            "api": ["1"], "destination": ["12 King & Queen Road, Lagos, Lagos State, Nigeria"],
        })
        self.assertIn("Get directions", html)
        self.assertIn(url, message.body)
        self.assertIn("Music &amp; Friends", html)
        self.assertEqual(message.attachments[0].filename, "ticket-123.png")
        self.assertEqual(message.attachments[0].content, b"ticket-image")
        self.assertNotIn("linear-gradient", html)

    def test_no_directions_without_location_or_for_online_events(self):
        for changes in (dict(address=None, city=" ", state="", country=None), dict(type="ONLINE")):
            with self.subTest(changes=changes):
                send_ticket_email(self.make_order(**changes))
                self.assertNotIn("Get directions", mail.outbox[-1].alternatives[0].content)
                self.assertNotIn("google.com/maps", mail.outbox[-1].body)

    def test_shared_notification_preserves_lines_and_escapes_content(self):
        html = render_to_string("emails/notification.html", {
            "heading": "Confirm your email", "body": "Code: 123456\n<script>unsafe</script>",
            "action_label": "Continue", "action_url": "https://example.com/confirm",
        })
        self.assertIn("Code: 123456<br>", html)
        self.assertNotIn("<script>", html)
        self.assertIn('href="https://example.com/confirm"', html)

    def test_online_template_preserves_private_link(self):
        html = render_to_string("emails/online_event_link.html", {
            "event": SimpleNamespace(title="Online workshop", meeting_platform="Zoom",
                                     meeting_link="https://example.com/join?x=1&y=2"),
            "updated": True,
        })
        self.assertIn("Your event link has changed", html)
        self.assertIn('href="https://example.com/join?x=1&amp;y=2"', html)
        self.assertIn("Do not share or forward", html)
        self.assertNotIn("Get directions", html)
