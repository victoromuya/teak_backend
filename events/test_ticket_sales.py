from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from unittest.mock import patch

from events.models import Event, TicketType
from orders.models import Order, OrderItem, Ticket


class TicketSalesTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(email="sales-owner@example.com", is_organizer=True)
        self.buyer = users.objects.create_user(email="sales-buyer@example.com")
        self.event = Event.objects.create(
            organizer=self.owner, title="Sales", description="Test",
            end_date=timezone.localdate(), paid_event=True,
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event, name="Entry", price=100, quantity=10, remaining=9,
        )
        self.order = Order.objects.create(
            user=self.buyer, event=self.event, total_amount=100,
            reference="previous-purchase", status="paid",
        )
        OrderItem.objects.create(order=self.order, ticket_type=self.ticket_type, quantity=1, price=100)
        self.ticket = Ticket.objects.create(order=self.order, ticket_type=self.ticket_type)
        self.url = f"/api/ticketype/{self.ticket_type.pk}/"

    def disable(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(self.url, {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.ticket_type.refresh_from_db()
        self.assertFalse(self.ticket_type.is_active)
        self.assertEqual(self.ticket_type.remaining, 9)

    def test_disable_after_purchase_preserves_ticket_and_owner_access(self):
        self.disable()
        self.assertEqual(self.client.get(f"/api/events/{self.event.pk}/tickets/").data[0]["is_active"], False)
        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get("/api/orders/my-tickets/").data[0]["ticket_code"], str(self.ticket.ticket_code))
        self.client.force_authenticate(self.owner)
        response = self.client.post(f"/api/events/{self.event.pk}/scan-ticket/", {
            "ticket_code": str(self.ticket.ticket_code),
        }, format="json")
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(self.url, {"is_active": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])

    def test_disabled_types_hidden_from_buyers_on_all_public_endpoints(self):
        self.disable()
        for user in (None, self.buyer):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get("/api/ticketype/").data, [])
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self.client.get(f"/api/events/{self.event.pk}/tickets/").data, [])
            self.assertEqual(self.client.get(f"/api/events/{self.event.pk}/").data["ticket_prices"], [])

    @patch("orders.views.requests.post")
    @patch("orders.views.generate_tickets")
    def test_disabled_types_cannot_be_ordered_by_id_paid_or_free(self, generate, payment):
        self.disable()
        self.client.force_authenticate(self.buyer)
        for price in (100, 0):
            self.ticket_type.price = price
            self.ticket_type.save(update_fields=["price"])
            response = self.client.post("/api/orders/", {
                "event": self.event.pk,
                "items": [{"ticket_type": self.ticket_type.pk, "quantity": 1}],
            }, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("no longer available", response.data["message"])
        self.assertEqual(Order.objects.count(), 1)
        payment.assert_not_called()
        generate.assert_not_called()

    def test_other_organizer_cannot_disable_ticket_sales(self):
        other = get_user_model().objects.create_user(email="sales-other@example.com", is_organizer=True)
        self.client.force_authenticate(other)
        self.assertEqual(self.client.patch(self.url, {"is_active": False}, format="json").status_code, 403)
        self.ticket_type.refresh_from_db()
        self.assertTrue(self.ticket_type.is_active)
