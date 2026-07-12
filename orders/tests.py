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
