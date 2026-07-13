from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework import status
from rest_framework.test import APITestCase

from orders.models import Order, Ticket
from .models import Event, TicketType
from .views import TicketTypeViewSet


class TicketTypePermissionTests(SimpleTestCase):
    def test_list_uses_permission_instances(self):
        view = TicketTypeViewSet()
        view.action = "list"

        permissions = view.get_permissions()

        self.assertEqual(len(permissions), 1)
        self.assertIsInstance(permissions[0], IsAuthenticatedOrReadOnly)

    def test_retrieve_uses_permission_instances(self):
        view = TicketTypeViewSet()
        view.action = "retrieve"

        permissions = view.get_permissions()

        self.assertEqual(len(permissions), 1)
        self.assertIsInstance(permissions[0], IsAuthenticatedOrReadOnly)


class SoldTicketsPermissionTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.other_organizer = user_model.objects.create_user(
            email="other-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.buyer = user_model.objects.create_user(
            email="buyer@example.com",
            password="password123",
        )
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Organizer Event",
            description="Permission test event.",
        )
        ticket_type = TicketType.objects.create(
            event=self.event,
            name="General",
            price="1000.00",
        )
        order = Order.objects.create(
            user=self.buyer,
            event=self.event,
            reference="sold-ticket-permission-test",
            total_amount="1000.00",
            status="paid",
        )
        Ticket.objects.create(order=order, ticket_type=ticket_type)
        self.url = f"/api/events/{self.event.pk}/sold-tickets/"

    def test_sold_tickets_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_sold_tickets_rejects_another_organizer(self):
        self.client.force_authenticate(self.other_organizer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_event_organizer_can_list_sold_tickets(self):
        self.client.force_authenticate(self.organizer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
