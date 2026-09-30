from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from events.models import Event, TicketType
from .models import Order
from .processing_fees import payment_breakdown
from .services import InvalidPaymentError, finalize_paystack_payment
from .views import event_withdrawal_balance


LOCAL_FEES = dict(
    PAYSTACK_FEE_PERCENTAGE="1.5", PAYSTACK_FEE_FLAT_AMOUNT="100.00",
    PAYSTACK_FEE_FLAT_THRESHOLD="2500.00", PAYSTACK_FEE_CAP="2000.00",
    TICKET_PLATFORM_FEE_PERCENTAGE="6.00",
)


@override_settings(**LOCAL_FEES)
class ProcessingFeeCalculationTests(SimpleTestCase):
    def test_free_small_threshold_and_capped_payments(self):
        for subtotal, expected in [
            ("0.00", "0.00"), ("100.00", "101.53"),
            ("2462.49", "2499.99"), ("2462.50", "2601.53"),
            ("2500.00", "2639.60"), ("10000.00", "10253.81"),
            ("130000.00", "132000.00"), ("500000.00", "502000.00"),
        ]:
            with self.subTest(subtotal=subtotal):
                fee, payable = payment_breakdown(Decimal(subtotal))
                self.assertEqual(payable, Decimal(expected))
                self.assertEqual(fee + Decimal(subtotal), payable)
                self.assertLessEqual(fee, Decimal("2000.00"))
                if payable:
                    provider_fee = min(
                        payable * Decimal("0.015") + (100 if payable >= 2500 else 0),
                        Decimal("2000.00"),
                    )
                    self.assertGreaterEqual(payable - provider_fee, Decimal(subtotal))

    @override_settings(PAYSTACK_FEE_PERCENTAGE="2", PAYSTACK_FEE_FLAT_AMOUNT="0")
    def test_uses_configured_pricing(self):
        self.assertEqual(payment_breakdown(Decimal("10000.00")), (Decimal("204.09"), Decimal("10204.09")))

    @override_settings(PAYSTACK_FEE_PERCENTAGE="0", PAYSTACK_FEE_FLAT_AMOUNT="0")
    def test_no_fee_when_pricing_is_zero(self):
        self.assertEqual(payment_breakdown(Decimal("10000.00")), (Decimal("0.00"), Decimal("10000.00")))


@override_settings(**LOCAL_FEES)
class ProcessingFeeCheckoutTests(APITestCase):
    def setUp(self):
        self.organizer = get_user_model().objects.create_user(
            email="fee-organizer@example.com", password="password", is_organizer=True,
        )
        self.buyer = get_user_model().objects.create_user(email="fee-buyer@example.com", password="password")
        self.event = Event.objects.create(organizer=self.organizer, title="Fee checkout", description="Test")
        self.ticket = TicketType.objects.create(event=self.event, name="Entry", price="10000.00", quantity=10, remaining=10)
        self.client.force_authenticate(self.buyer)

    def create_checkout(self, **extra):
        with patch("orders.views.requests.post") as initialize:
            initialize.return_value.json.return_value = {
                "status": True, "data": {"authorization_url": "https://pay.example/checkout"},
            }
            response = self.client.post("/api/orders/", {
                "event": self.event.pk,
                "items": [{"ticket_type": self.ticket.pk, "quantity": 1}], **extra,
            }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return Order.objects.get(pk=response.data["order_id"]), response, initialize

    def test_quote_initialization_and_reload_use_same_server_total(self):
        order, response, initialize = self.create_checkout(processing_fee="0", payment_amount="1")
        self.assertEqual(order.total_amount, Decimal("10000.00"))
        self.assertEqual(order.processing_fee, Decimal("253.81"))
        self.assertEqual(order.payment_amount, Decimal("10253.81"))
        self.assertEqual(initialize.call_args.kwargs["json"]["amount"], 1025381)
        self.assertEqual(response.data["payment_amount"], order.payment_amount)
        retrieved = self.client.get(f"/api/orders/{order.pk}/")
        self.assertEqual(Decimal(retrieved.data["payment_amount"]), order.payment_amount)
        self.assertEqual(Decimal(retrieved.data["processing_fee"]), order.processing_fee)

    @patch("orders.services._generate_tickets", return_value=[])
    def test_verifies_full_payment_but_splits_only_ticket_revenue(self, generate):
        order, _, _ = self.create_checkout()
        payment = {"reference": order.reference, "status": "success", "currency": "NGN", "amount": 1000000}
        with self.assertRaises(InvalidPaymentError):
            finalize_paystack_payment(order.reference, payment)
        order.refresh_from_db()
        self.assertEqual(order.status, "pending")
        self.assertIsNone(order.organizer_revenue)
        # Subsequent configuration changes must not change an agreed payment.
        with override_settings(PAYSTACK_FEE_PERCENTAGE="10"):
            paid, _, first = finalize_paystack_payment(order.reference, {**payment, "amount": 1025381})
            _, _, second = finalize_paystack_payment(order.reference, {**payment, "amount": 1025381})
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(paid.organizer_revenue, Decimal("9400.00"))
        self.assertEqual(paid.platform_revenue, Decimal("600.00"))
        self.assertEqual(event_withdrawal_balance(self.event)["available_amount"], Decimal("9400.00"))

    @patch("orders.views.generate_tickets", return_value=[])
    def test_free_orders_have_no_fee_or_paystack_charge(self, generate):
        self.ticket.price = Decimal("0")
        self.ticket.save(update_fields=["price"])
        order, response, initialize = self.create_checkout()
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.payment_amount, Decimal("0.00"))
        self.assertEqual(order.processing_fee, Decimal("0.00"))
        initialize.assert_not_called()

    def test_fee_is_per_payment_not_per_ticket(self):
        order, _, _ = self.create_checkout(items=[{"ticket_type": self.ticket.pk, "quantity": 2}])
        self.assertEqual(order.total_amount, Decimal("20000.00"))
        self.assertEqual(order.payment_amount, Decimal("20406.10"))

    def test_nonpositive_quantity_cannot_create_a_payment(self):
        for quantity in (0, -1):
            response = self.client.post("/api/orders/", {
                "event": self.event.pk, "items": [{"ticket_type": self.ticket.pk, "quantity": quantity}],
            }, format="json")
            self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_migration_preserves_old_paid_and_pending_charges(self):
        for status in ("paid", "pending"):
            Order.objects.create(user=self.buyer, event=self.event, reference=status, total_amount="10000.00", status=status)
        Order.objects.update(payment_amount=None)
        migration = import_module("orders.migrations.0006_order_processing_fee")
        migration.preserve_existing_payment_amounts(apps, SimpleNamespace(connection=connection))
        for order in Order.objects.all():
            self.assertEqual(order.payment_amount, Decimal("10000.00"))
            self.assertEqual(order.processing_fee, Decimal("0.00"))
