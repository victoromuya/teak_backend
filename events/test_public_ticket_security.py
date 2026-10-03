from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Event, TicketType


class PublicTicketSecurityTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(email="visibility-owner@example.com", is_organizer=True)
        self.buyer = users.objects.create_user(email="visibility-buyer@example.com")
        self.events = []
        self.tickets = []
        for index, flags in enumerate(({}, {"is_active": False}, {"is_deleted": True}, {"end_date": timezone.localdate() - timedelta(days=1)})):
            fields = {"end_date": timezone.localdate(), **flags}
            event = Event.objects.create(organizer=self.owner, title=f"Visibility {index}", description="Test", **fields)
            self.events.append(event)
            self.tickets.append(TicketType.objects.create(event=event, name="Entry", price=10))

    def test_public_and_customer_reads_hide_nonpublic_ticket_types(self):
        for user in (None, self.buyer):
            self.client.force_authenticate(user=user)
            response = self.client.get("/api/ticketype/")
            self.assertEqual([row["id"] for row in response.data], [self.tickets[0].pk])
            for ticket in self.tickets[1:]:
                self.assertEqual(self.client.get(f"/api/ticketype/{ticket.pk}/").status_code, 404)
            self.assertEqual(self.client.get(f"/api/ticketype/{self.tickets[0].pk}/").status_code, 200)

    def test_owner_can_manage_drafts_but_other_organizer_cannot_read_them(self):
        self.client.force_authenticate(self.owner)
        url = f"/api/ticketype/{self.tickets[1].pk}/"
        self.assertEqual(self.client.patch(url, {"name": "Updated draft"}, format="json").status_code, 200)
        other = get_user_model().objects.create_user(email="other-visibility@example.com", is_organizer=True)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(url).status_code, 404)

    @patch("events.views.send_email")
    def test_sender_quota_applies_across_ips(self, send):
        self.client.force_authenticate(self.buyer)
        for index in range(6):
            response = self.client.post(f"/api/events/{self.events[0].pk}/contact-organizer/", {
                "subject": "Question", "message": "A test question about the event.",
            }, format="json", REMOTE_ADDR=f"192.0.2.{index + 1}")
            self.assertEqual(response.status_code, 200 if index < 5 else 429)
        self.assertEqual(send.call_count, 5)
        self.assertIn("Retry-After", response)

    @patch("events.views.send_email")
    def test_recipient_quota_applies_across_senders_and_events(self, send):
        second = Event.objects.create(organizer=self.owner, title="Another event", description="Test", end_date=timezone.localdate())
        for index in range(21):
            buyer = get_user_model().objects.create_user(email=f"enquirer-{index}@example.com")
            self.client.force_authenticate(buyer)
            event = self.events[0] if index % 2 else second
            response = self.client.post(f"/api/events/{event.pk}/contact-organizer/", {
                "subject": "Question", "message": "A test question about the event.",
            }, format="json", REMOTE_ADDR=f"192.0.2.{index + 1}")
            self.assertEqual(response.status_code, 200 if index < 20 else 429)
        self.assertEqual(send.call_count, 20)
