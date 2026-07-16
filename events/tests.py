from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework import status
from rest_framework.test import APITestCase

from orders.models import Order, Ticket
from .models import Event, TicketType
from .views import TicketTypeViewSet


class EventCreationDateValidationTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="event-date-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.client.force_authenticate(self.organizer)
        self.url = "/api/events/"

    def event_payload(self, start_date, end_date):
        return {
            "title": "Scheduled Event",
            "description": "Tests event creation date validation.",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

    def test_rejects_event_with_past_start_date(self):
        today = timezone.localdate()

        response = self.client.post(
            self.url,
            self.event_payload(today - timedelta(days=1), today + timedelta(days=1)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            str(response.data["message"][0]),
            "Events cannot be created using past dates.",
        )
        self.assertIn("start_date", response.data)
        self.assertFalse(Event.objects.filter(organizer=self.organizer).exists())

    def test_rejects_event_with_past_end_date(self):
        today = timezone.localdate()

        response = self.client.post(
            self.url,
            self.event_payload(today, today - timedelta(days=1)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_date", response.data)
        self.assertFalse(Event.objects.filter(organizer=self.organizer).exists())

    def test_allows_event_starting_today(self):
        today = timezone.localdate()

        response = self.client.post(
            self.url,
            self.event_payload(today, today + timedelta(days=1)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class EventVisibilityTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="visibility-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.other_organizer = user_model.objects.create_user(
            email="visibility-other@example.com",
            password="password123",
            is_organizer=True,
        )
        today = timezone.localdate()
        self.upcoming_event = Event.objects.create(
            organizer=self.other_organizer,
            title="Upcoming Event",
            description="Visible publicly.",
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=3),
        )
        self.ongoing_event = Event.objects.create(
            organizer=self.other_organizer,
            title="Ongoing Event",
            description="Still visible publicly.",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        self.past_event = Event.objects.create(
            organizer=self.organizer,
            title="Past Event",
            description="Visible only to its organizer through events.",
            start_date=today - timedelta(days=3),
            end_date=today - timedelta(days=2),
        )

    def test_public_list_only_contains_ongoing_and_upcoming_events(self):
        response = self.client.get("/api/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event_ids = {event["id"] for event in response.data}
        self.assertEqual(
            event_ids,
            {self.upcoming_event.id, self.ongoing_event.id},
        )

    def test_organizer_can_list_and_retrieve_their_past_event(self):
        self.client.force_authenticate(self.organizer)

        list_response = self.client.get("/api/events/")
        detail_response = self.client.get(f"/api/events/{self.past_event.id}/")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertIn(
            self.past_event.id,
            {event["id"] for event in list_response.data},
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)

    def test_public_cannot_retrieve_a_past_event(self):
        response = self.client.get(f"/api/events/{self.past_event.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


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


class TicketTypeDateValidationTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="ticket-date-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        today = timezone.localdate()
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Dated Event",
            description="Ticket date validation event.",
            start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=7),
        )
        self.client.force_authenticate(self.organizer)
        self.url = "/api/ticketype/"

    def ticket_payload(self, sales_expiry_date):
        return {
            "event": self.event.id,
            "name": "General",
            "price": "1000.00",
            "quantity": 100,
            "sales_expiry_date": sales_expiry_date.isoformat(),
        }

    def test_rejects_sales_expiry_before_event_start_date(self):
        expiry = timezone.now() + timedelta(days=4)

        response = self.client.post(
            self.url,
            self.ticket_payload(expiry),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sales_expiry_date", response.data)
        self.assertEqual(
            str(response.data["message"][0]),
            "Please choose a ticket sales expiry date on or after "
            f"{self.event.start_date:%B %d, %Y}. This is the event start date.",
        )

    def test_rejects_sales_expiry_after_event_end_date(self):
        expiry = timezone.now() + timedelta(days=8)

        response = self.client.post(
            self.url,
            self.ticket_payload(expiry),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sales_expiry_date", response.data)
        self.assertEqual(
            str(response.data["message"][0]),
            "Please choose a ticket sales expiry date on or before "
            f"{self.event.end_date:%B %d, %Y}. This is the event end date.",
        )

    def test_accepts_sales_expiry_within_event_dates(self):
        expiry = timezone.now() + timedelta(days=6)

        response = self.client.post(
            self.url,
            self.ticket_payload(expiry),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


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
