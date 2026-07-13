from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from events.models import Event, TicketType
from .models import Order, Ticket


class PurchasedTicketsEndpointTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email="buyer@example.com",
            password="password123",
        )
        self.other_user = user_model.objects.create_user(
            email="other@example.com",
            password="password123",
        )
        self.organizer = user_model.objects.create_user(
            email="organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Test Event",
            description="An event used by the API test.",
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name="VIP",
            price="5000.00",
        )

    def create_ticket(self, user, order_status="paid"):
        order = Order.objects.create(
            user=user,
            event=self.event,
            reference=f"ref-{user.pk}-{order_status}",
            total_amount="5000.00",
            status=order_status,
        )
        return Ticket.objects.create(order=order, ticket_type=self.ticket_type)

    def test_returns_only_authenticated_users_paid_tickets(self):
        purchased_ticket = self.create_ticket(self.user)
        self.create_ticket(self.other_user)
        self.create_ticket(self.user, order_status="pending")
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/orders/my-tickets/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["ticket_code"], str(purchased_ticket.ticket_code))
        self.assertEqual(response.data[0]["ticket_type"], "VIP")
        self.assertEqual(response.data[0]["event"]["title"], "Test Event")

    def test_requires_authentication(self):
        response = self.client.get("/api/orders/my-tickets/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class OrderEventTicketTypeValidationTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.buyer = user_model.objects.create_user(
            email="cross-event-buyer@example.com",
            password="password123",
        )
        organizer = user_model.objects.create_user(
            email="cross-event-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.requested_event = Event.objects.create(
            organizer=organizer,
            title="Requested Event",
            description="The event submitted on the order.",
        )
        other_event = Event.objects.create(
            organizer=organizer,
            title="Other Event",
            description="Owns the selected ticket type.",
        )
        self.other_event_ticket_type = TicketType.objects.create(
            event=other_event,
            name="Other Event VIP",
            price="5000.00",
        )

    def test_rejects_ticket_type_from_another_event(self):
        self.client.force_authenticate(self.buyer)

        response = self.client.post(
            "/api/orders/",
            {
                "event": self.requested_event.pk,
                "items": [
                    {
                        "ticket_type": self.other_event_ticket_type.pk,
                        "quantity": 1,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("items", response.data)
        self.assertFalse(Order.objects.filter(user=self.buyer).exists())


class OrganizerOrderReportingTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="reporting-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.other_organizer = user_model.objects.create_user(
            email="other-reporting-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.buyer = user_model.objects.create_user(
            email="reporting-buyer@example.com",
            password="password123",
        )
        self.first_event = self.create_event(self.organizer, "First Event")
        self.second_event = self.create_event(self.organizer, "Second Event")
        other_event = self.create_event(self.other_organizer, "Other Event")

        first_ticket_type = self.create_ticket_type(self.first_event, "First VIP")
        second_ticket_type = self.create_ticket_type(self.second_event, "Second VIP")
        other_ticket_type = self.create_ticket_type(other_event, "Other VIP")

        first_paid_order = self.create_order(
            self.first_event,
            "organizer-first-paid",
            "300.00",
            "paid",
        )
        self.create_tickets(first_paid_order, first_ticket_type, 2)

        second_paid_order = self.create_order(
            self.second_event,
            "organizer-second-paid",
            "100.00",
            "paid",
        )
        self.create_tickets(second_paid_order, second_ticket_type, 1)

        self.create_order(
            self.first_event,
            "organizer-first-pending",
            "999.00",
            "pending",
        )

        other_order = self.create_order(
            other_event,
            "other-organizer-paid",
            "500.00",
            "paid",
        )
        self.create_tickets(other_order, other_ticket_type, 1)

    def create_event(self, organizer, title):
        return Event.objects.create(
            organizer=organizer,
            title=title,
            description=f"{title} description.",
        )

    def create_ticket_type(self, event, name):
        return TicketType.objects.create(
            event=event,
            name=name,
            price="100.00",
        )

    def create_order(self, event, reference, amount, order_status):
        return Order.objects.create(
            user=self.buyer,
            event=event,
            reference=reference,
            total_amount=amount,
            status=order_status,
        )

    def create_tickets(self, order, ticket_type, quantity):
        for _ in range(quantity):
            Ticket.objects.create(order=order, ticket_type=ticket_type)

    def test_lists_only_orders_for_the_organizers_events(self):
        self.client.force_authenticate(self.organizer)

        response = self.client.get("/api/orders/organizer-orders/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        returned_events = {order["event"] for order in response.data}
        self.assertEqual(
            returned_events,
            {self.first_event.pk, self.second_event.pk},
        )

    def test_can_filter_organizer_orders_by_owned_event(self):
        self.client.force_authenticate(self.organizer)

        response = self.client.get(
            "/api/orders/organizer-orders/",
            {"event": self.first_event.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertTrue(
            all(order["event"] == self.first_event.pk for order in response.data)
        )

    def test_summary_counts_only_paid_sales_for_owned_events(self):
        self.client.force_authenticate(self.organizer)

        response = self.client.get("/api/orders/organizer-summary/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_events"], 2)
        self.assertEqual(response.data["total_revenue"], Decimal("400.00"))
        self.assertEqual(response.data["total_paid_orders"], 2)
        self.assertEqual(response.data["total_tickets_sold"], 3)
        self.assertEqual(len(response.data["events"]), 2)

    def test_summary_rejects_non_organizers(self):
        self.client.force_authenticate(self.buyer)

        response = self.client.get("/api/orders/organizer-summary/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
