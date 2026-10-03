from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models.query import QuerySet
from django.utils import timezone
from rest_framework.test import APITestCase

from orders.models import Order, Ticket
from .models import Event, TicketType


class TicketScanSecurityTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.organizer = users.objects.create_user(email="scanner@example.com", is_organizer=True)
        self.buyer = users.objects.create_user(email="scan-buyer@example.com")
        self.event = Event.objects.create(organizer=self.organizer, title="Scan event", description="Test")
        self.order = Order.objects.create(user=self.buyer, event=self.event, reference="scan-security", total_amount=10, status="paid")
        ticket_type = TicketType.objects.create(event=self.event, name="Entry", price=10)
        self.ticket = Ticket.objects.create(order=self.order, ticket_type=ticket_type)
        self.url = f"/api/events/{self.event.pk}/scan-ticket/"
        self.client.force_authenticate(self.organizer)

    def scan(self):
        return self.client.post(self.url, {"ticket_code": str(self.ticket.ticket_code)}, format="json")

    def test_ticket_can_only_be_scanned_once(self):
        self.assertEqual(self.scan().status_code, 200)
        self.assertEqual(self.scan().status_code, 400)
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.is_used)
        self.assertEqual(self.ticket.scanned_by_id, self.organizer.pk)

    def test_stale_scan_cannot_overwrite_a_concurrent_admission(self):
        original_get = QuerySet.get
        winning_time = timezone.now()

        def get_with_competing_scan(queryset, *args, **kwargs):
            obj = original_get(queryset, *args, **kwargs)
            if queryset.model is Ticket:
                Ticket.objects.filter(pk=obj.pk).update(
                    is_used=True, scanned_at=winning_time, scanned_by=self.organizer,
                )
            return obj

        with patch.object(QuerySet, "get", get_with_competing_scan):
            response = self.scan()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.scanned_at, winning_time)

    def test_unpaid_ticket_cannot_be_scanned(self):
        Order.objects.filter(pk=self.order.pk).update(status="pending")
        self.assertEqual(self.scan().status_code, 400)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_used)

    def test_other_organizer_cannot_scan_ticket(self):
        other = get_user_model().objects.create_user(email="other-scanner@example.com", is_organizer=True)
        self.client.force_authenticate(other)
        self.assertIn(self.scan().status_code, (403, 404))
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_used)
