from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.core import mail
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

    def test_rejects_end_date_earlier_than_start_date(self):
        today = timezone.localdate()

        response = self.client.post(
            self.url,
            self.event_payload(
                today + timedelta(days=2),
                today + timedelta(days=1),
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            str(response.data["message"][0]),
            "The event end date cannot be earlier than the start date.",
        )
        self.assertEqual(
            str(response.data["end_date"][0]),
            "Please choose an event end date that is the same as or later "
            "than the start date.",
        )
        self.assertFalse(Event.objects.filter(organizer=self.organizer).exists())


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
        self.admin = user_model.objects.create_user(
            email="visibility-admin@example.com",
            password="password123",
            is_staff=True,
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
            description="Visible only through organizer management.",
            start_date=today - timedelta(days=3),
            end_date=today - timedelta(days=2),
        )
        self.inactive_event = Event.objects.create(
            organizer=self.organizer,
            title="Draft Event",
            description="Not publicly visible.",
            start_date=today + timedelta(days=4),
            end_date=today + timedelta(days=5),
            is_active=False,
        )

    def test_public_list_only_contains_ongoing_and_upcoming_events(self):
        response = self.client.get("/api/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event_ids = {event["id"] for event in response.data}
        self.assertEqual(
            event_ids,
            {self.upcoming_event.id, self.ongoing_event.id},
        )

    def test_public_list_places_newest_event_first(self):
        newest_event = Event.objects.create(
            organizer=self.other_organizer,
            title="Newest Upcoming Event",
            description="Should be prominent on the homepage.",
            start_date=timezone.localdate() + timedelta(days=4),
            end_date=timezone.localdate() + timedelta(days=5),
        )

        response = self.client.get("/api/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["id"], newest_event.id)

    def test_logged_in_organizer_public_list_still_excludes_private_events(self):
        self.client.force_authenticate(self.organizer)

        list_response = self.client.get("/api/events/")
        my_events_response = self.client.get("/api/events/my_events/")
        detail_response = self.client.get(f"/api/events/{self.past_event.id}/")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {event["id"] for event in list_response.data},
            {self.upcoming_event.id, self.ongoing_event.id},
        )
        self.assertEqual(my_events_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {event["id"] for event in my_events_response.data},
            {self.past_event.id, self.inactive_event.id},
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)

    def test_logged_in_admin_public_list_still_excludes_private_events(self):
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {event["id"] for event in response.data},
            {self.upcoming_event.id, self.ongoing_event.id},
        )

    def test_public_cannot_retrieve_a_past_event(self):
        response = self.client.get(f"/api/events/{self.past_event.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_list_deactivates_past_events(self):
        self.assertTrue(self.past_event.is_active)

        self.client.get("/api/events/")

        self.past_event.refresh_from_db()
        self.assertFalse(self.past_event.is_active)


class ContactOrganizerTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="contact-organizer@example.com",
            password="password123",
            first_name="Event",
            last_name="Organizer",
            is_organizer=True,
        )
        self.buyer = user_model.objects.create_user(
            email="contact-buyer@example.com",
            password="password123",
            first_name="Ticket",
            last_name="Buyer",
        )
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Contactable Event",
            description="Contact endpoint test event.",
            start_date=timezone.localdate() + timedelta(days=2),
            end_date=timezone.localdate() + timedelta(days=3),
            is_active=True,
        )
        self.url = f"/api/events/{self.event.pk}/contact-organizer/"
        self.payload = {
            "subject": "Accessibility question",
            "message": "Is the venue wheelchair accessible?",
        }

    def test_requires_authentication(self):
        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(len(mail.outbox), 0)

    def test_prospective_buyer_can_contact_organizer_for_public_event(self):
        self.client.force_authenticate(self.buyer)

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.organizer.email])
        self.assertEqual(mail.outbox[0].reply_to, [self.buyer.email])
        self.assertIn(self.payload["message"], mail.outbox[0].body)

    def test_paid_order_holder_can_contact_organizer_after_event_is_inactive(self):
        self.event.is_active = False
        self.event.save(update_fields=["is_active"])
        Order.objects.create(
            user=self.buyer,
            event=self.event,
            reference="contact-paid-order",
            total_amount="0.00",
            status="paid",
        )
        self.client.force_authenticate(self.buyer)

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

    def test_non_purchaser_cannot_contact_organizer_for_inactive_event(self):
        self.event.is_active = False
        self.event.save(update_fields=["is_active"])
        self.client.force_authenticate(self.buyer)

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(len(mail.outbox), 0)

    def test_rejects_subject_header_injection(self):
        self.client.force_authenticate(self.buyer)
        payload = {**self.payload, "subject": "Question\nBcc: victim@example.com"}

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)


class EventManagementAuthorizationTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="event-manager@example.com",
            password="password123",
            is_organizer=True,
        )
        self.buyer = user_model.objects.create_user(
            email="event-buyer@example.com",
            password="password123",
        )
        self.admin = user_model.objects.create_user(
            email="event-admin@example.com",
            password="password123",
            is_staff=True,
        )
        self.other_organizer = user_model.objects.create_user(
            email="other-event-manager@example.com",
            password="password123",
            is_organizer=True,
        )

    def create_event(self, *, past=False, active=True):
        today = timezone.localdate()
        if past:
            start_date, end_date = today - timedelta(days=2), today - timedelta(days=1)
        else:
            start_date, end_date = today + timedelta(days=2), today + timedelta(days=3)
        return Event.objects.create(
            organizer=self.organizer,
            title="Managed Event",
            description="Authorization test event.",
            start_date=start_date,
            end_date=end_date,
            is_active=active,
        )

    def add_order(self, event, reference="managed-event-order"):
        return Order.objects.create(
            user=self.buyer,
            event=event,
            reference=reference,
            total_amount="500.00",
            status="paid",
        )

    def test_organizer_cannot_change_featured_status(self):
        event = self.create_event()
        self.client.force_authenticate(self.organizer)

        response = self.client.patch(
            f"/api/events/{event.pk}/",
            {"is_featured": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        event.refresh_from_db()
        self.assertFalse(event.is_featured)

    def test_organizer_can_create_event_with_default_featured_status(self):
        self.client.force_authenticate(self.organizer)
        today = timezone.localdate()

        response = self.client.post(
            "/api/events/",
            {
                "title": "Organizer Event",
                "description": "An event created with the featured default.",
                "start_date": today + timedelta(days=2),
                "end_date": today + timedelta(days=3),
                "is_featured": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(Event.objects.get(pk=response.data["id"]).is_featured)

    def test_organizer_cannot_create_featured_event(self):
        self.client.force_authenticate(self.organizer)
        today = timezone.localdate()

        response = self.client.post(
            "/api/events/",
            {
                "title": "Featured Organizer Event",
                "description": "An organizer must not feature their own event.",
                "start_date": today + timedelta(days=2),
                "end_date": today + timedelta(days=3),
                "is_featured": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Event.objects.filter(title="Featured Organizer Event").exists())

    def test_organizer_can_deactivate_published_event_with_orders(self):
        event = self.create_event()
        self.add_order(event)
        self.client.force_authenticate(self.organizer)

        response = self.client.patch(
            f"/api/events/{event.pk}/",
            {"is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertFalse(event.is_active)

    def test_organizer_can_reactivate_their_event(self):
        event = self.create_event(active=False)
        self.client.force_authenticate(self.organizer)

        response = self.client.patch(
            f"/api/events/{event.pk}/",
            {"is_active": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertTrue(event.is_active)

    def test_organizer_can_update_published_event_details(self):
        event = self.create_event()
        self.client.force_authenticate(self.organizer)

        response = self.client.patch(
            f"/api/events/{event.pk}/",
            {
                "title": "Updated Published Event",
                "description": "Updated after publication.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertEqual(event.title, "Updated Published Event")
        self.assertEqual(event.description, "Updated after publication.")

    def test_other_organizer_cannot_update_event(self):
        event = self.create_event()
        self.client.force_authenticate(self.other_organizer)

        response = self.client.patch(
            f"/api/events/{event.pk}/",
            {"title": "Unauthorized change"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        event.refresh_from_db()
        self.assertEqual(event.title, "Managed Event")

    def test_update_rejects_end_date_before_start_date(self):
        event = self.create_event()
        self.client.force_authenticate(self.organizer)

        response = self.client.patch(
            f"/api/events/{event.pk}/",
            {"end_date": (event.start_date - timedelta(days=1)).isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_date", response.data)

    def test_organizer_can_create_and_update_ticket_type_for_owned_event(self):
        event = self.create_event()
        self.client.force_authenticate(self.organizer)
        expiry = timezone.now() + timedelta(days=1)

        create_response = self.client.post(
            "/api/ticketype/",
            {
                "event": event.pk,
                "name": "General Admission",
                "price": "1500.00",
                "quantity": 50,
                "sales_expiry_date": expiry.isoformat(),
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        ticket_id = create_response.data["id"]
        update_response = self.client.patch(
            f"/api/ticketype/{ticket_id}/",
            {"name": "Early Bird"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["name"], "Early Bird")

    def test_admin_can_change_featured_status(self):
        event = self.create_event()
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            f"/api/admin/events/{event.pk}/",
            {"is_featured": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertTrue(event.is_featured)

    def test_organizer_cannot_delete_published_future_event_with_orders(self):
        event = self.create_event()
        self.add_order(event)
        self.client.force_authenticate(self.organizer)

        response = self.client.delete(f"/api/events/{event.pk}/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        event.refresh_from_db()
        self.assertFalse(event.is_deleted)

    def test_deactivating_event_does_not_bypass_order_deletion_rule(self):
        event = self.create_event(active=False)
        self.add_order(event)
        self.client.force_authenticate(self.organizer)

        response = self.client.delete(f"/api/events/{event.pk}/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        event.refresh_from_db()
        self.assertFalse(event.is_deleted)

    def test_organizer_can_remove_past_event_without_losing_order_history(self):
        event = self.create_event(past=True)
        order = self.add_order(event)
        self.client.force_authenticate(self.organizer)

        response = self.client.delete(f"/api/events/{event.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        event.refresh_from_db()
        self.assertTrue(event.is_deleted)
        self.assertFalse(event.is_active)
        self.assertTrue(Order.objects.filter(pk=order.pk, event=event).exists())
        self.assertEqual(
            self.client.get(f"/api/events/{event.pk}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_admin_can_remove_future_event_without_losing_order_history(self):
        event = self.create_event()
        order = self.add_order(event)
        self.client.force_authenticate(self.admin)

        response = self.client.delete(f"/api/admin/events/{event.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        event.refresh_from_db()
        self.assertTrue(event.is_deleted)
        self.assertTrue(Order.objects.filter(pk=order.pk, event=event).exists())


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


class FreeEventTicketCreationTests(APITestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            email="free-event-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.client.force_authenticate(self.organizer)

    def test_free_event_creation_creates_real_ticket_type(self):
        response = self.client.post(
            "/api/events/",
            {
                "title": "Community Meetup",
                "description": "A free event.",
                "paid_event": False,
                "free_ticket_quantity": 25,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ticket_type = TicketType.objects.get(event_id=response.data["id"], price=0)
        self.assertEqual(ticket_type.name, "Free Entry")
        self.assertEqual(ticket_type.quantity, 25)
        self.assertEqual(ticket_type.remaining, 25)

    def test_updating_legacy_free_event_repairs_missing_ticket_type(self):
        event = Event.objects.create(
            organizer=self.organizer,
            title="Legacy Free Event",
            description="Created before free tickets were enforced.",
            paid_event=False,
        )

        response = self.client.patch(
            f"/api/events/{event.pk}/",
            {"description": "Updated legacy event."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(event.ticket_types.filter(price=0).exists())

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

    def test_accepts_sales_expiry_before_event_start_date(self):
        expiry = timezone.now() + timedelta(days=4)

        response = self.client.post(
            self.url,
            self.ticket_payload(expiry),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["event"], self.event.id)

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
