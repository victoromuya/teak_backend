from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from events.models import Event, TicketType
from .limits import MAX_TICKETS_PER_ORDER
from .models import Order, OrderItem, Ticket


class CheckoutLimitTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="limit@example.com")
        self.event = Event.objects.create(organizer=self.user, title="Limit", description="Test", end_date=timezone.localdate())
        self.tickets = [TicketType.objects.create(event=self.event, name=f"Entry {i}", price=0, quantity=1000000, remaining=1000000) for i in range(2)]
        self.client.force_authenticate(self.user)

    def submit(self, quantities):
        return self.client.post("/api/orders/", {
            "event": self.event.pk,
            "items": [{"ticket_type": self.tickets[i % 2].pk, "quantity": quantity} for i, quantity in enumerate(quantities)],
        }, format="json")

    @patch("orders.views.requests.post")
    @patch("orders.views.generate_tickets")
    def test_oversized_baskets_never_create_orders_or_call_providers(self, generate, payment):
        for price in (0, 100):
            TicketType.objects.filter(event=self.event).update(price=price)
            for quantities in ([1000000], [MAX_TICKETS_PER_ORDER + 1], [MAX_TICKETS_PER_ORDER, 1], [1] * (MAX_TICKETS_PER_ORDER + 1)):
                with self.subTest(price=price, quantities=quantities):
                    self.assertEqual(self.submit(quantities).status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.assertFalse(Ticket.objects.exists())
        self.assertEqual(list(TicketType.objects.values_list("remaining", flat=True)), [1000000, 1000000])
        generate.assert_not_called()
        payment.assert_not_called()

    @patch("orders.views.generate_tickets", return_value=[])
    def test_free_basket_at_limit_is_allowed(self, generate):
        self.assertEqual(self.submit([MAX_TICKETS_PER_ORDER - 1, 1]).status_code, 201)
        self.assertEqual(sum(Order.objects.get().items.values_list("quantity", flat=True)), MAX_TICKETS_PER_ORDER)
        generate.assert_called_once()

    @patch("orders.views.requests.post")
    def test_paid_basket_at_limit_is_allowed(self, payment):
        TicketType.objects.filter(event=self.event).update(price=100)
        payment.return_value.json.return_value = {"status": True, "data": {"authorization_url": "https://pay.example/checkout"}}
        self.assertEqual(self.submit([MAX_TICKETS_PER_ORDER]).status_code, 201)
        payment.assert_called_once()

    def test_checkout_requests_are_limited_per_account(self):
        for index in range(11):
            response = self.client.post("/api/orders/", {}, format="json", REMOTE_ADDR=f"192.0.2.{index + 1}")
            self.assertEqual(response.status_code, 400 if index < 10 else 429)
        self.assertIn("Retry-After", response)

    def test_platform_config_publishes_limit(self):
        self.assertEqual(self.client.get("/api/platform-config/").data["max_tickets_per_order"], MAX_TICKETS_PER_ORDER)
