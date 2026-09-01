import csv
import requests
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponse
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Order, OrderItem, Ticket, WithdrawalRequest
from .serializers import (
    OrderCreateSerializer,
    OrderSerializer,
    PurchasedTicketSerializer,
    WithdrawalRequestSerializer,
)

from django.db import transaction
from rest_framework.decorators import action, api_view, permission_classes

from django.utils import timezone
from datetime import timedelta

from django.core.files import File
from io import BytesIO
import qrcode
from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from drf_spectacular.utils import extend_schema, OpenApiExample
from events.models import Event
from events.permissions import IsOrganizer
from .services import (
    InsufficientInventoryError,
    InvalidPaymentError,
    OrderNotFoundError,
    finalize_paystack_payment,
)
from glob_utils.send_email import send_email
from accounts.permissions import IsAdmin


def withdrawal_fee_percentage():
    try:
        value = Decimal(str(settings.TICKET_PLATFORM_FEE_PERCENTAGE))
    except (InvalidOperation, TypeError):
        value = Decimal("5.00")
    return min(max(value, Decimal("0")), Decimal("100"))


def event_withdrawal_balance(event):
    gross = Order.objects.filter(event=event, status="paid").aggregate(
        total=Sum("total_amount")
    )["total"] or Decimal("0.00")
    fee_percentage = withdrawal_fee_percentage()
    fee_amount = (gross * fee_percentage / Decimal("100")).quantize(Decimal("0.01"))
    net = gross - fee_amount
    pending_amount = WithdrawalRequest.objects.filter(
        event=event, status="pending"
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    withdrawn_amount = WithdrawalRequest.objects.filter(
        event=event, status="completed"
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    reserved = pending_amount + withdrawn_amount
    return {
        "gross_revenue": gross,
        "fee_percentage": fee_percentage,
        "fee_amount": fee_amount,
        "net_revenue": net,
        "reserved_amount": reserved,
        "pending_amount": pending_amount,
        "withdrawn_amount": withdrawn_amount,
        "available_amount": max(net - reserved, Decimal("0.00")),
    }


class WithdrawalRequestViewSet(ModelViewSet):
    serializer_class = WithdrawalRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        if self.action in ["complete", "reject"]:
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = WithdrawalRequest.objects.select_related("organizer", "event", "completed_by")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(organizer=self.request.user)

    @action(detail=False, methods=["get"])
    def balance(self, request):
        event = get_object_or_404(
            Event,
            pk=request.query_params.get("event"),
            organizer=request.user,
            is_deleted=False,
        )
        return Response(event_withdrawal_balance(event))

    def create(self, request, *args, **kwargs):
        if not getattr(request.user, "is_organizer", False):
            return Response(
                {"detail": "Only organizers can request withdrawals."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            event = get_object_or_404(
                Event.objects.select_for_update(),
                pk=request.data.get("event"),
                organizer=request.user,
                is_deleted=False,
            )
            balance = event_withdrawal_balance(event)
            if balance["available_amount"] <= 0:
                return Response(
                    {"detail": "There is no available revenue to withdraw for this event."},
                    status=status.HTTP_409_CONFLICT,
                )
            withdrawal = serializer.save(
                organizer=request.user,
                event=event,
                email=request.user.email,
                gross_revenue=balance["gross_revenue"],
                fee_percentage=balance["fee_percentage"],
                fee_amount=balance["fee_amount"],
                amount=balance["available_amount"],
            )

        send_email(
            "Withdrawal request received",
            f'Your withdrawal request for "{event.title}" has been received. '
            f'We will fund {withdrawal.account_name} with NGN {withdrawal.amount:,.2f} '
            "within 24–48 hours.",
            request.user.email,
            heading="Your withdrawal is being processed",
            action_label="View event",
            action_url=f'{settings.FRONTEND_URL.rstrip("/")}/organizer/event/{event.pk}',
        )
        return Response(self.get_serializer(withdrawal).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        with transaction.atomic():
            withdrawal = WithdrawalRequest.objects.select_for_update().select_related(
                "organizer", "event"
            ).get(pk=pk)
            if withdrawal.status != "pending":
                return Response(
                    {"detail": "Only pending withdrawals can be completed."},
                    status=status.HTTP_409_CONFLICT,
                )
            withdrawal.status = "completed"
            withdrawal.completed_at = timezone.now()
            withdrawal.completed_by = request.user
            withdrawal.admin_note = request.data.get("admin_note", "")
            withdrawal.save(update_fields=["status", "completed_at", "completed_by", "admin_note"])

        send_email(
            "Withdrawal completed",
            f'Your withdrawal of NGN {withdrawal.amount:,.2f} for '
            f'"{withdrawal.event.title}" has been paid to '
            f'{withdrawal.bank_name} account {withdrawal.account_number}.',
            withdrawal.email,
            heading="Your payment has been made",
        )
        return Response(self.get_serializer(withdrawal).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        withdrawal = self.get_object()
        if withdrawal.status != "pending":
            return Response({"detail": "Only pending withdrawals can be rejected."}, status=409)
        withdrawal.status = "rejected"
        withdrawal.admin_note = request.data.get("admin_note", "")
        withdrawal.save(update_fields=["status", "admin_note"])
        return Response(self.get_serializer(withdrawal).data)


@extend_schema(
    tags=["Orders"],
    examples=[
        OpenApiExample(
            "Create Order Example",
            value={
                "event": 2,
                "items": [
                    {
                        "ticket_type": 2,
                        "quantity": 1
                    }
                ]
            },
            request_only=True,
        )
    ]
)
class OrderViewSet(ModelViewSet):
    queryset = Order.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderSerializer

    def get_queryset(self):
        user = self.request.user

        expired_time = timezone.now() - timedelta(minutes=10)

        Order.objects.filter(
            status="pending",
            created_at__lt=expired_time
        ).update(status="expired")

        if user.is_staff:
            return Order.objects.all()
        if self.action == "destroy" and getattr(user, "is_organizer", False):
            return Order.objects.filter(
                Q(user=user) | Q(event__organizer=user)
            ).distinct()
        return Order.objects.filter(user=user)

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT", detail="Orders are immutable.")

    def partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PATCH", detail="Orders are immutable.")

    def destroy(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status == "paid":
            return Response(
                {"detail": "Paid orders are permanent financial records and cannot be deleted."},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = serializer.save()

        # ==========================
        # FREE EVENT / FREE TICKETS
        # ==========================
        if order.total_amount == 0:

            with transaction.atomic():

                order_items = order.items.select_related(
                    "ticket_type"
                ).select_for_update()

                # Reduce ticket stock
                for item in order_items:

                    ticket_type = item.ticket_type

                    if ticket_type.remaining < item.quantity:
                        return Response(
                            {
                                "error": f"Insufficient tickets for {ticket_type.name}"
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    ticket_type.remaining -= item.quantity
                    ticket_type.save(update_fields=["remaining"])

                # Mark order as completed
                order.status = "paid"
                order.verified_at = timezone.now()
                order.save(update_fields=["status", "verified_at"])

                # Generate QR tickets
                tickets = generate_tickets(order)

            ticket_data = [
                {
                    "ticket_code": ticket.ticket_code,
                    "qr_code_url": request.build_absolute_uri(ticket.qr_image.url),
                    "ticket_type": ticket.ticket_type.name,
                }
                for ticket in tickets
            ]

            return Response(
                {
                    "message": "Free ticket booked successfully.",
                    "order_id": order.id,
                    "order_reference": order.reference,
                    "reference": order.reference,
                    "status": order.status,
                    "tickets_count": len(ticket_data),
                    "tickets": ticket_data,
                },
                status=status.HTTP_201_CREATED,
            )

        # ==========================
        # PAID EVENT
        # ==========================

        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "email": request.user.email,
                "amount": int(order.total_amount * 100),
                "reference": order.reference,
                "callback_url": settings.PAYSTACK_CALLBACK_URL,
            },
        )

        data = response.json()

        if not data.get("status"):
            return Response(
                {
                    "error": "Unable to initialize payment.",
                    "details": data.get("message"),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "order_id": order.id,
                "payment_url": data["data"]["authorization_url"],
                "reference": order.reference,
            },
            status=status.HTTP_201_CREATED,
        )
    

    @action(detail=False, methods=['get'])
    def pending(self, request):
        queryset = self.get_queryset().filter(status='pending')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["Tickets"],
        description="List tickets purchased by the authenticated user",
        responses=PurchasedTicketSerializer(many=True),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="my-tickets",
        permission_classes=[IsAuthenticated],
    )
    def my_tickets(self, request):
        tickets = Ticket.objects.filter(
            order__user=request.user,
            order__status="paid",
        ).select_related(
            "ticket_type",
            "order__event",
        ).order_by("-created_at")

        serializer = PurchasedTicketSerializer(
            tickets,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)

    @extend_schema(
        tags=["Organizer"],
        description="List orders placed for events owned by the authenticated organizer",
        responses=OrderSerializer(many=True),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="organizer-orders",
        permission_classes=[IsOrganizer],
    )
    def organizer_orders(self, request):
        orders = Order.objects.filter(
            event__organizer=request.user,
        ).select_related(
            "event",
            "user",
        ).prefetch_related("items").order_by("-created_at")

        event_id = request.query_params.get("event")
        if event_id:
            orders = orders.filter(event_id=event_id)

        page = self.paginate_queryset(orders)
        if page is not None:
            serializer = OrderSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["Organizer"],
        description="Download one CSV row for every successfully issued ticket",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="organizer-attendees",
        permission_classes=[IsOrganizer],
    )
    def organizer_attendees(self, request):
        event_id = request.query_params.get("event")
        if not event_id:
            return Response(
                {"detail": "Choose an event before downloading its attendee CSV."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = get_object_or_404(
            Event,
            pk=event_id,
            organizer=request.user,
            is_deleted=False,
        )
        tickets = Ticket.objects.filter(
            order__event=event,
            order__status="paid",
        ).select_related(
            "order__user",
            "order__event",
            "ticket_type",
            "scanned_by",
        ).order_by("order__event__title", "order__created_at", "created_at")

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        safe_event_id = str(event.pk)
        response["Content-Disposition"] = (
            f'attachment; filename="tickfirst-event-{safe_event_id}-attendees.csv"'
        )
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow([
            "Event ID", "Event Title", "Event Start Date", "Event End Date",
            "Attendee User ID", "Attendee Name", "Attendee Email", "Order ID",
            "Order Reference", "Order Status", "Order Amount (NGN)", "Order Date",
            "Payment Verified At", "Ticket Type", "Ticket Price (NGN)",
            "Ticket Code", "Ticket Status", "Ticket Issued At", "Scanned At",
            "Scanned By",
        ])

        def format_datetime(value):
            return timezone.localtime(value).isoformat() if value else ""

        for ticket in tickets:
            order = ticket.order
            event = order.event
            attendee = order.user
            scanner = ticket.scanned_by
            writer.writerow([
                event.pk,
                event.title,
                event.start_date.isoformat() if event.start_date else "",
                event.end_date.isoformat() if event.end_date else "",
                attendee.pk,
                attendee.get_full_name() or attendee.email,
                attendee.email,
                order.pk,
                order.reference,
                order.status,
                order.total_amount,
                format_datetime(order.created_at),
                format_datetime(order.verified_at),
                ticket.ticket_type.name,
                ticket.ticket_type.price,
                ticket.ticket_code,
                "Used" if ticket.is_used else "Valid",
                format_datetime(ticket.created_at),
                format_datetime(ticket.scanned_at),
                (scanner.get_full_name() or scanner.email) if scanner else "",
            ])

        return response

    @extend_schema(
        tags=["Organizer"],
        description=(
            "Return paid revenue and sold-ticket totals for all events owned "
            "by the authenticated organizer"
        ),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="organizer-summary",
        permission_classes=[IsOrganizer],
    )
    def organizer_summary(self, request):
        current_year = timezone.localdate().year
        events = list(
            Event.objects.filter(organizer=request.user)
            .order_by("-created_at")
            .values("id", "title")
        )
        paid_orders = Order.objects.filter(
            event__organizer=request.user,
            status="paid",
        )

        order_stats = {
            row["event_id"]: row
            for row in paid_orders.values("event_id").annotate(
                total_revenue=Sum("total_amount"),
                total_paid_orders=Count("id"),
            )
        }
        ticket_stats = {
            row["order__event_id"]: row["total_tickets_sold"]
            for row in Ticket.objects.filter(
                order__event__organizer=request.user,
                order__status="paid",
            )
            .values("order__event_id")
            .annotate(total_tickets_sold=Count("id"))
        }
        revenue_by_month = {
            row["created_at__month"]: row["total"]
            for row in paid_orders.filter(created_at__year=current_year)
            .values("created_at__month")
            .annotate(total=Sum("total_amount"))
        }
        tickets_by_month = {
            row["created_at__month"]: row["total"]
            for row in Ticket.objects.filter(
                order__event__organizer=request.user,
                order__status="paid",
                created_at__year=current_year,
            )
            .values("created_at__month")
            .annotate(total=Count("id"))
        }

        event_summaries = []
        total_revenue = Decimal("0.00")
        total_paid_orders = 0
        total_tickets_sold = 0

        for event in events:
            event_order_stats = order_stats.get(event["id"], {})
            event_revenue = event_order_stats.get(
                "total_revenue",
                Decimal("0.00"),
            )
            event_paid_orders = event_order_stats.get("total_paid_orders", 0)
            event_tickets_sold = ticket_stats.get(event["id"], 0)

            total_revenue += event_revenue
            total_paid_orders += event_paid_orders
            total_tickets_sold += event_tickets_sold

            event_summaries.append(
                {
                    "event_id": event["id"],
                    "event_title": event["title"],
                    "total_revenue": event_revenue,
                    "total_paid_orders": event_paid_orders,
                    "total_tickets_sold": event_tickets_sold,
                }
            )

        return Response(
            {
                "total_events": len(events),
                "total_revenue": total_revenue,
                "total_paid_orders": total_paid_orders,
                "total_tickets_sold": total_tickets_sold,
                "monthly_revenue": [
                    revenue_by_month.get(month, Decimal("0.00"))
                    for month in range(1, 13)
                ],
                "monthly_tickets_sold": [
                    tickets_by_month.get(month, 0) for month in range(1, 13)
                ],
                "reporting_year": current_year,
                "events": event_summaries,
            }
        )


@extend_schema(
    tags=["Orders"],
    description="Verify Payment",
    responses={200: None}
)
@api_view(["GET"])
@permission_classes([])   # Allow any - Paystack redirects without auth
def verify_payment(request, reference=None):

    # Get reference from query params (for Paystack callback) or URL kwargs (for backward compatibility)
    if reference is None:
        reference = request.GET.get('reference')
    if not reference:
        return Response(
            {"error": "Reference not provided"},
            status=400
        )

    # Paystack remains the source of truth; fulfillment is handled below.
    verify_url = f"https://api.paystack.co/transaction/verify/{reference}"

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
    }

    try:
        paystack_response = requests.get(
            verify_url,
            headers=headers,
            timeout=10
        )

        paystack_data = paystack_response.json()

    except (requests.RequestException, ValueError):
        return Response(
            {"error": "Payment verification failed"},
            status=502
        )

    # 4️⃣ Validate Paystack response
    if not paystack_data.get("status"):
        return Response(
            {"error": "Invalid Paystack response"},
            status=400
        )

    try:
        order, tickets, finalized = finalize_paystack_payment(
            reference,
            paystack_data.get("data", {}),
        )
    except OrderNotFoundError as exc:
        return Response({"error": str(exc)}, status=404)
    except (InvalidPaymentError, InsufficientInventoryError) as exc:
        return Response({"error": str(exc)}, status=400)

    ticket_data = [{
        "ticket_code": ticket.ticket_code,
        "qr_code_url": request.build_absolute_uri(ticket.qr_image.url),
        "ticket_type": ticket.ticket_type.name,
    } for ticket in tickets]
    return Response({
        "message": (
            "Payment verified successfully"
            if finalized else "Payment already verified"
        ),
        "order_id": order.id,
        "order_reference": order.reference,
        "tickets": ticket_data,
    })

@api_view(["GET"])
@permission_classes([])   # Allow any - redirect from Paystack
def payment_success(request):
    """
    Redirect to payment verification endpoint with reference from query params.
    Paystack redirects to this URL with ?trxref=XXX&reference=YYY
    """
    reference = request.GET.get('reference')
    if not reference:
        return Response(
            {"error": "Reference not provided"},
            status=400
        )
    # Redirect to verification endpoint with reference as query parameter
    return redirect(f'/api/orders/verify/?reference={reference}')



def generate_tickets(order):
    order_items = OrderItem.objects.filter(order=order)
    generated_tickets = []

    for item in order_items:
        ticket_type = item.ticket_type
        for i in range(item.quantity):
            ticket = Ticket.objects.create(
                order=order,
                ticket_type=ticket_type
            )

            qr = qrcode.make(str(ticket.ticket_code))
            buffer = BytesIO()
            qr.save(buffer, format="PNG")
            
            # --- ADD THIS LINE ---
            buffer.seek(0) 
            # ---------------------

            filename = f"{ticket.ticket_code}.png"
            # Now Cloudinary will see the data in the buffer
            ticket.qr_image.save(filename, File(buffer), save=True)
            generated_tickets.append(ticket)

    send_ticket_email(order)
    return generated_tickets



def send_ticket_email(order):
    tickets = order.ticket_set.all()
    subject = "Your Ticket Confirmation"
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [order.user.email]

    text_content = f"""
Hi,

Your payment was successful.

Order Reference: {order.reference}
Tickets: {tickets.count()}

Please view this email in HTML to see your QR codes.
"""

    html_content = render_to_string("emails/ticket_confirmation.html", {
        "order": order,
        "tickets": tickets,
        "ticket_count": tickets.count(),
        "frontend_url": settings.FRONTEND_URL.rstrip("/"),
    })

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=recipient_list,
    )
    msg.attach_alternative(html_content, "text/html")

    for i, ticket in enumerate(tickets):
        if ticket.qr_image:
            # ✅ Use .read() directly on the field to get data from Cloudinary
            image_data = ticket.qr_image.read()
            
            msg.attach(f"{ticket.ticket_code}.png", image_data, "image/png")
    try:
        msg.send(fail_silently=False)
        print("email sent!")
    except Exception as e:
        print(f"Error: {e}")
