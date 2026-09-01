import csv
from decimal import Decimal
import hashlib
import hmac
import io
import json
import threading
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.core import mail
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APITestCase

from events.models import Event, TicketType
from accounts.models import EmailOTP
from .models import Order, OrderItem, Ticket, WithdrawalRequest
from .services import InvalidPaymentError, finalize_paystack_payment


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    TICKET_PLATFORM_FEE_PERCENTAGE="10.00",
)
class WithdrawalRequestTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.organizer = users.objects.create_user(
            email="payout-organizer@example.com", password="password123",
            first_name="Ada", last_name="Organizer", is_organizer=True,
        )
        self.admin = users.objects.create_user(
            email="payout-admin@example.com", password="password123", is_staff=True,
        )
        self.buyer = users.objects.create_user(
            email="payout-buyer@example.com", password="password123",
        )
        self.event = Event.objects.create(
            organizer=self.organizer, title="Payout Event", description="Revenue event."
        )
        Order.objects.create(
            user=self.buyer, event=self.event, reference="payout-paid-order",
            total_amount="10000.00", status="paid",
        )
        Order.objects.create(
            user=self.buyer, event=self.event, reference="payout-pending-order",
            total_amount="5000.00", status="pending",
        )
        self.payload = {
            "event": self.event.pk,
            "contact": "+2348000000000",
            "account_number": "0123456789",
            "bank_name": "Example Bank",
            "account_name": "Ada Organizer",
        }

    def test_organizer_requests_net_event_revenue(self):
        self.client.force_authenticate(self.organizer)
        response = self.client.post("/api/withdrawals/", self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        withdrawal = WithdrawalRequest.objects.get()
        self.assertEqual(withdrawal.gross_revenue, Decimal("10000.00"))
        self.assertEqual(withdrawal.fee_percentage, Decimal("10.00"))
        self.assertEqual(withdrawal.fee_amount, Decimal("1000.00"))
        self.assertEqual(withdrawal.amount, Decimal("9000.00"))
        self.assertEqual(withdrawal.email, self.organizer.email)
        self.assertEqual(len(mail.outbox), 1)

    def test_pending_request_reserves_available_balance(self):
        self.client.force_authenticate(self.organizer)
        self.client.post("/api/withdrawals/", self.payload, format="json")

        response = self.client.post("/api/withdrawals/", self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(WithdrawalRequest.objects.count(), 1)

    def test_admin_completes_request_and_sends_email(self):
        self.client.force_authenticate(self.organizer)
        created = self.client.post("/api/withdrawals/", self.payload, format="json")
        mail.outbox.clear()
        self.client.force_authenticate(self.admin)

        response = self.client.post(f"/api/withdrawals/{created.data['id']}/complete/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.organizer.email])

        self.client.force_authenticate(self.organizer)
        balance = self.client.get(
            "/api/withdrawals/balance/", {"event": self.event.pk}
        )
        history = self.client.get("/api/withdrawals/")
        self.assertEqual(balance.data["available_amount"], Decimal("0.00"))
        self.assertEqual(balance.data["withdrawn_amount"], Decimal("9000.00"))
        self.assertEqual(len(history.data), 1)
        self.assertEqual(history.data[0]["status"], "completed")

    def test_organizer_cannot_withdraw_another_organizers_event(self):
        other = get_user_model().objects.create_user(
            email="other-payout-organizer@example.com", password="password123",
            is_organizer=True,
        )
        self.client.force_authenticate(other)

        response = self.client.post("/api/withdrawals/", self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


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

    def test_order_creation_requires_authentication(self):
        self.client.force_authenticate(user=None)

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

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Order.objects.exists())

    @patch("orders.views.requests.post")
    def test_verified_guest_is_automatically_signed_in_before_order(self, paystack_post):
        paystack_post.return_value.json.return_value = {
            "status": True,
            "data": {"authorization_url": "https://pay.example/checkout"},
        }
        ticket_type = TicketType.objects.create(
            event=self.requested_event,
            name="Guest VIP",
            price="100.00",
            remaining=5,
        )
        otp = "123456"
        guest_email = "automatic-guest@example.com"
        EmailOTP.objects.create(
            email=guest_email,
            otp=make_password(otp),
            first_name="Automatic",
            last_name="Guest",
            purpose="guest_checkout",
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        verification = self.client.post(
            "/api/auth/verify-email/",
            {
                "email": guest_email,
                "otp": otp,
                "purpose": "guest_checkout",
            },
            format="json",
        )

        self.assertEqual(verification.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", verification.data)
        self.assertTrue(
            get_user_model().objects.filter(email=guest_email).exists()
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {verification.data['access']}"
        )
        response = self.client.post(
            "/api/orders/",
            {
                "event": self.requested_event.pk,
                "items": [{"ticket_type": ticket_type.pk, "quantity": 1}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Order.objects.filter(user__email=guest_email).exists())


class OrderTicketSalesExpiryTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.buyer = user_model.objects.create_user(
            email="sales-expiry-buyer@example.com",
            password="password123",
        )
        organizer = user_model.objects.create_user(
            email="sales-expiry-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.event = Event.objects.create(
            organizer=organizer,
            title="Sales Expiry Event",
            description="Tests exact ticket sale closing times.",
        )
        self.client.force_authenticate(self.buyer)

    def create_ticket_type(self, name, sales_expiry_date):
        return TicketType.objects.create(
            event=self.event,
            name=name,
            price="1000.00",
            sales_expiry_date=sales_expiry_date,
        )

    def place_order(self, ticket_type):
        return self.client.post(
            "/api/orders/",
            {
                "event": self.event.pk,
                "items": [{"ticket_type": ticket_type.pk, "quantity": 1}],
            },
            format="json",
        )

    def test_rejects_order_after_ticket_sales_expiry_time(self):
        ticket_type = self.create_ticket_type(
            "Expired VIP",
            timezone.now() - timedelta(seconds=1),
        )

        response = self.place_order(ticket_type)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        expected_message = (
            "Expired VIP tickets are no longer available for sale because "
            "the sales period has ended."
        )
        self.assertEqual(str(response.data["message"]), expected_message)
        self.assertEqual(str(response.data["items"]), expected_message)
        self.assertFalse(Order.objects.filter(user=self.buyer).exists())

    @patch("orders.views.requests.post")
    def test_allows_order_before_ticket_sales_expiry_time(self, paystack_post):
        paystack_post.return_value.json.return_value = {
            "status": True,
            "data": {"authorization_url": "https://pay.example/checkout"},
        }
        ticket_type = self.create_ticket_type(
            "Available VIP",
            timezone.now() + timedelta(hours=1),
        )

        response = self.place_order(ticket_type)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Order.objects.filter(user=self.buyer).exists())


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
        OrderItem.objects.create(
            order=order,
            ticket_type=ticket_type,
            quantity=quantity,
            price=ticket_type.price,
        )
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
        first_paid = next(
            order for order in response.data
            if order["reference"] == "organizer-first-paid"
        )
        self.assertEqual(first_paid["tickets_count"], 2)

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
        current_month = timezone.localdate().month - 1
        self.assertEqual(response.data["monthly_revenue"][current_month], Decimal("400.00"))
        self.assertEqual(response.data["monthly_tickets_sold"][current_month], 3)
        self.assertEqual(len(response.data["events"]), 2)

    def test_summary_rejects_non_organizers(self):
        self.client.force_authenticate(self.buyer)

        response = self.client.get("/api/orders/organizer-summary/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_attendee_export_contains_only_paid_issued_tickets(self):
        self.client.force_authenticate(self.organizer)

        response = self.client.get(
            "/api/orders/organizer-attendees/",
            {"event": self.first_event.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["Order Reference"] for row in rows},
            {"organizer-first-paid"},
        )
        self.assertEqual(
            {row["Attendee Email"] for row in rows},
            {self.buyer.email},
        )
        self.assertTrue(all(row["Ticket Code"] for row in rows))

    def test_attendee_export_rejects_non_organizers(self):
        self.client.force_authenticate(self.buyer)

        response = self.client.get("/api/orders/organizer-attendees/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_attendee_export_requires_an_event(self):
        self.client.force_authenticate(self.organizer)

        response = self.client.get("/api/orders/organizer-attendees/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_attendee_export_rejects_another_organizers_event(self):
        other_event = Event.objects.exclude(organizer=self.organizer).first()
        self.client.force_authenticate(self.organizer)

        response = self.client.get(
            "/api/orders/organizer-attendees/",
            {"event": other_event.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OrderHistoryProtectionTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.buyer = user_model.objects.create_user(
            email="history-buyer@example.com",
            password="password123",
        )
        organizer = user_model.objects.create_user(
            email="history-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.event = Event.objects.create(
            organizer=organizer,
            title="History Event",
            description="Order history tests.",
        )
        self.client.force_authenticate(self.buyer)

    def create_order(self, reference, order_status):
        return Order.objects.create(
            user=self.buyer,
            event=self.event,
            reference=reference,
            total_amount="100.00",
            status=order_status,
        )

    def test_paid_order_cannot_be_deleted(self):
        order = self.create_order("paid-history", "paid")
        response = self.client.delete(f"/api/orders/{order.pk}/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())

    def test_orders_cannot_be_modified_through_customer_api(self):
        order = self.create_order("pending-history", "pending")
        response = self.client.patch(
            f"/api/orders/{order.pk}/",
            {"status": "paid", "total_amount": "1.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        order.refresh_from_db()
        self.assertEqual(order.status, "pending")
        self.assertEqual(order.total_amount, Decimal("100.00"))

    def test_unpaid_order_can_be_deleted(self):
        order = self.create_order("cancelled-before-payment", "pending")
        response = self.client.delete(f"/api/orders/{order.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Order.objects.filter(pk=order.pk).exists())


@skipUnlessDBFeature("has_select_for_update")
class PaymentConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        organizer = user_model.objects.create_user(
            email="concurrency-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        buyer = user_model.objects.create_user(
            email="concurrency-buyer@example.com",
            password="password123",
        )
        event = Event.objects.create(
            organizer=organizer,
            title="Concurrent Payment Event",
            description="Concurrent finalization test.",
        )
        self.ticket_type = TicketType.objects.create(
            event=event,
            name="Concurrent VIP",
            price="50.00",
            quantity=10,
            remaining=10,
        )
        self.order = Order.objects.create(
            user=buyer,
            event=event,
            reference="concurrent-payment",
            total_amount="100.00",
            status="pending",
        )
        OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            quantity=2,
            price="50.00",
        )
        self.payment_data = {
            "reference": self.order.reference,
            "status": "success",
            "amount": 10000,
            "currency": "NGN",
        }

    @patch("orders.services._generate_tickets")
    def test_simultaneous_callbacks_fulfill_order_once(self, generate_tickets):
        generate_tickets.side_effect = lambda order, items: [
            Ticket.objects.create(
                order=order,
                ticket_type_id=self.ticket_type.pk,
                qr_image=f"ticketQR/concurrent-{index}.png",
            )
            for index in range(2)
        ]
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def finalize():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                results.append(
                    finalize_paystack_payment(
                        self.order.reference,
                        self.payment_data,
                    )[2]
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=finalize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(errors)
        self.assertEqual(sorted(results), [False, True])
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.remaining, 8)
        self.assertEqual(Ticket.objects.filter(order=self.order).count(), 2)
        self.assertEqual(generate_tickets.call_count, 1)


class PaystackFinalizationTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organizer = user_model.objects.create_user(
            email="payment-organizer@example.com",
            password="password123",
            is_organizer=True,
        )
        self.buyer = user_model.objects.create_user(
            email="payment-buyer@example.com",
            password="password123",
        )
        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Payment Event",
            description="Payment finalization tests.",
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name="VIP",
            price="50.00",
            quantity=10,
            remaining=10,
        )
        self.order = Order.objects.create(
            user=self.buyer,
            event=self.event,
            reference="paystack-ref-1",
            total_amount="100.00",
            status="pending",
        )
        OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            quantity=2,
            price="50.00",
        )
        self.payment_data = {
            "reference": self.order.reference,
            "status": "success",
            "amount": 10000,
            "currency": "NGN",
        }

    @patch("orders.services._generate_tickets")
    def test_finalizes_inventory_tickets_and_order_once(self, generate_tickets):
        generate_tickets.side_effect = lambda order, items: [
            Ticket.objects.create(
                order=order,
                ticket_type=self.ticket_type,
                qr_image=f"ticketQR/{index}.png",
            )
            for index in range(2)
        ]

        order, tickets, finalized = finalize_paystack_payment(
            self.order.reference,
            self.payment_data,
        )
        second_order, second_tickets, second_finalized = finalize_paystack_payment(
            self.order.reference,
            self.payment_data,
        )

        self.ticket_type.refresh_from_db()
        self.assertTrue(finalized)
        self.assertFalse(second_finalized)
        self.assertEqual(order.pk, second_order.pk)
        self.assertEqual(order.status, "paid")
        self.assertEqual(self.ticket_type.remaining, 8)
        self.assertEqual(len(tickets), 2)
        self.assertEqual(len(second_tickets), 2)
        self.assertEqual(Ticket.objects.filter(order=self.order).count(), 2)
        self.assertEqual(generate_tickets.call_count, 1)

    @patch("orders.services._generate_tickets")
    def test_rejects_amount_mismatch_without_mutation(self, generate_tickets):
        payment_data = {**self.payment_data, "amount": 9999}

        with self.assertRaisesRegex(InvalidPaymentError, "amount mismatch"):
            finalize_paystack_payment(self.order.reference, payment_data)

        self.order.refresh_from_db()
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.order.status, "pending")
        self.assertEqual(self.ticket_type.remaining, 10)
        generate_tickets.assert_not_called()

    @patch("orders.views.requests.get")
    @patch("orders.services._generate_tickets")
    def test_verify_endpoint_uses_idempotent_finalization(
        self,
        generate_tickets,
        paystack_get,
    ):
        generate_tickets.side_effect = lambda order, items: [
            Ticket.objects.create(
                order=order,
                ticket_type=self.ticket_type,
                qr_image=f"ticketQR/{index}.png",
            )
            for index in range(2)
        ]
        paystack_get.return_value.json.return_value = {
            "status": True,
            "data": self.payment_data,
        }

        first = self.client.get(f"/api/orders/verify/{self.order.reference}/")
        second = self.client.get(f"/api/orders/verify/{self.order.reference}/")

        self.ticket_type.refresh_from_db()
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["message"], "Payment already verified")
        self.assertEqual(self.ticket_type.remaining, 8)
        self.assertEqual(Ticket.objects.filter(order=self.order).count(), 2)

    @patch("orders.webhook.finalize_paystack_payment")
    def test_signed_webhook_delegates_to_shared_service(self, finalize):
        body = json.dumps({
            "event": "charge.success",
            "data": self.payment_data,
        }).encode()
        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(),
            body,
            hashlib.sha512,
        ).hexdigest()

        response = self.client.post(
            "/api/payments/webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        finalize.assert_called_once_with(self.order.reference, self.payment_data)

    @patch("orders.webhook.finalize_paystack_payment")
    def test_webhook_rejects_invalid_signature(self, finalize):
        response = self.client.post(
            "/api/payments/webhook/",
            data=json.dumps({"event": "charge.success", "data": self.payment_data}),
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="invalid",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        finalize.assert_not_called()

    @patch("orders.services._generate_tickets")
    def test_signed_webhook_rejects_amount_mismatch_without_mutation(
        self,
        generate_tickets,
    ):
        invalid_data = {**self.payment_data, "amount": 1}
        body = json.dumps({
            "event": "charge.success",
            "data": invalid_data,
        }).encode()
        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(),
            body,
            hashlib.sha512,
        ).hexdigest()

        response = self.client.post(
            "/api/payments/webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.order.refresh_from_db()
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.order.status, "pending")
        self.assertEqual(self.ticket_type.remaining, 10)
        generate_tickets.assert_not_called()
