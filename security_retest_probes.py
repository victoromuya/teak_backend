"""Isolated audit regression probes for the security findings.

Run explicitly: python manage.py test security_retest_probes --settings=tick_backend.test_settings
External email, ticket generation, and payment calls are mocked.
"""
from datetime import timedelta
from unittest.mock import patch
import threading

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.db import close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from events.models import Event, TicketType
from orders.models import Order, OrderItem, Ticket, WithdrawalRequest
from accounts.models import EmailOTP


class SecurityRetestProbes(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.organizer = users.objects.create_user(email="audit-owner@example.com", is_organizer=True)
        self.buyer = users.objects.create_user(email="audit-buyer@example.com", is_email_verified=True)
        self.event = Event.objects.create(
            organizer=self.organizer, title="Audit event", description="Test fixture",
            start_date=timezone.localdate(), end_date=timezone.localdate() + timedelta(days=1),
        )
        self.ticket_type = TicketType.objects.create(event=self.event, name="Audit entry", price=0, quantity=10, remaining=10)

    def test_anonymous_cannot_read_draft_ticket_types(self):
        Event.objects.filter(pk=self.event.pk).update(is_active=False)
        response = self.client.get(f"/api/ticketype/{self.ticket_type.pk}/")
        self.assertEqual(response.status_code, 404, f"Draft ticket disclosed: HTTP {response.status_code}")

    def test_anonymous_cannot_list_archived_ticket_types(self):
        self.event.archive()
        response = self.client.get("/api/ticketype/")
        self.assertEqual(response.status_code, 200)
        records = response.data if isinstance(response.data, list) else response.data["results"]
        self.assertNotIn(self.ticket_type.pk, [record["id"] for record in records])

    @patch("orders.views.generate_tickets", return_value=[])
    def test_free_checkout_rejects_excessive_ticket_count(self, generate):
        self.client.force_authenticate(self.organizer)
        created = self.client.post("/api/ticketype/", {
            "event": self.event.pk, "name": "Bulk free entry", "price": "0.00", "quantity": 1000000,
        }, format="json")
        self.assertEqual(created.status_code, 201)
        self.client.force_authenticate(self.buyer)
        response = self.client.post("/api/orders/", {
            "event": self.event.pk,
            "items": [{"ticket_type": created.data["id"], "quantity": 1000000}],
        }, format="json")
        self.assertIn(response.status_code, (400, 429), f"Million-ticket checkout accepted: HTTP {response.status_code}")
        generate.assert_not_called()
        self.assertFalse(Order.objects.exists())

    @patch("events.views.send_email")
    def test_contact_organizer_stops_repeated_email_requests(self, send):
        self.client.force_authenticate(self.buyer)
        codes = [self.client.post(f"/api/events/{self.event.pk}/contact-organizer/", {
            "subject": "Test enquiry", "message": "Local security audit; delivery is mocked.",
        }, format="json").status_code for _ in range(35)]
        self.assertIn(429, codes, f"All {send.call_count} email requests accepted without throttling")

    def test_login_rejects_json_array_without_server_error(self):
        self.client.raise_request_exception = False
        response = self.client.post("/api/auth/login/", [], format="json")
        self.assertEqual(response.status_code, 400, f"Malformed body returned HTTP {response.status_code}")

    def test_check_email_does_not_disclose_registration(self):
        known = self.client.post("/api/auth/check-email/", {"email": self.buyer.email}, format="json")
        unknown = self.client.post("/api/auth/check-email/", {"email": "not-registered@example.com"}, format="json")
        self.assertEqual(known.data, unknown.data)

    @patch("orders.views.requests.post")
    def test_rejected_checkout_never_initializes_payment(self, initialize):
        self.client.force_authenticate(self.buyer)
        for changes in ({"is_active": False}, {"is_deleted": True}, {"end_date": timezone.localdate() - timedelta(days=1)}):
            Event.objects.filter(pk=self.event.pk).update(is_active=True, is_deleted=False, end_date=timezone.localdate())
            Event.objects.filter(pk=self.event.pk).update(**changes)
            response = self.client.post("/api/orders/", {
                "event": self.event.pk, "items": [{"ticket_type": self.ticket_type.pk, "quantity": 1}],
            }, format="json")
            self.assertEqual(response.status_code, 400)
        initialize.assert_not_called()
        self.assertFalse(Order.objects.exists())


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentSecurityRetest(TransactionTestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model()
        self.admin = users.objects.create_user(email="concurrent-admin@example.com", is_staff=True, is_organizer=True)
        self.buyer = users.objects.create_user(email="concurrent-buyer@example.com", is_email_verified=True)
        self.event = Event.objects.create(organizer=self.admin, title="Concurrent audit", description="Fixture")
        self.order = Order.objects.create(user=self.buyer, event=self.event, reference="audit-concurrent", total_amount=100, status="paid")
        ticket_type = TicketType.objects.create(event=self.event, name="Entry", price=100)
        OrderItem.objects.create(order=self.order, ticket_type=ticket_type, quantity=1, price=100)
        self.ticket = Ticket.objects.create(order=self.order, ticket_type=ticket_type)

    def parallel(self, calls, user=None):
        barrier = threading.Barrier(len(calls))
        statuses, errors = [], []

        def run(url, data):
            close_old_connections()
            try:
                client = APIClient()
                if user is not None:
                    client.force_authenticate(user)
                barrier.wait(timeout=10)
                statuses.append(client.post(url, data, format="json").status_code)
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                close_old_connections()

        threads = [threading.Thread(target=run, args=call, daemon=True) for call in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads), "Concurrent request timed out")
        self.assertFalse(errors, errors)
        return sorted(statuses)

    @patch("orders.views.send_email")
    def test_real_concurrent_withdrawal_decisions(self, send):
        record = WithdrawalRequest.objects.create(
            organizer=self.admin, event=self.event, gross_revenue=100,
            fee_percentage=6, fee_amount=6, amount=94, email=self.admin.email,
        )
        results = self.parallel([
            (f"/api/withdrawals/{record.pk}/complete/", {}),
            (f"/api/withdrawals/{record.pk}/reject/", {}),
        ], self.admin)
        self.assertEqual(results, [200, 409])
        record.refresh_from_db()
        self.assertIn(record.status, ("completed", "rejected"))
        self.assertEqual(send.call_count, int(record.status == "completed"))

    def test_real_concurrent_ticket_scans(self):
        call = (f"/api/events/{self.event.pk}/scan-ticket/", {"ticket_code": str(self.ticket.ticket_code)})
        self.assertEqual(self.parallel([call, call], self.admin), [200, 400])

    def test_real_concurrent_refresh_replay(self):
        call = ("/api/auth/refresh/", {"refresh": str(RefreshToken.for_user(self.buyer))})
        self.assertEqual(self.parallel([call, call]), [200, 401])

    def test_real_concurrent_otp_guesses_cannot_exceed_limit(self):
        otp = EmailOTP.objects.create(
            email=self.buyer.email, otp=make_password("123456"), purpose="registration",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        call = ("/api/auth/verify-email/", {"email": self.buyer.email, "otp": "000000", "purpose": "registration"})
        self.assertEqual(self.parallel([call] * 6), [400] * 6)
        otp.refresh_from_db()
        self.assertEqual(otp.failed_attempts, 5)
