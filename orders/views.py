import requests
from django.conf import settings
from django.shortcuts import redirect
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from .models import Order, OrderItem, Ticket
from .serializers import (
    OrderCreateSerializer,
    OrderSerializer,
    PurchasedTicketSerializer,
)

from django.db import transaction
from rest_framework.decorators import action, api_view, permission_classes

from django.utils import timezone
from datetime import timedelta

from django.core.files import File
from io import BytesIO
import qrcode
from rest_framework import status
from django.core.mail import EmailMultiAlternatives
from email.mime.image import MIMEImage
from drf_spectacular.utils import extend_schema, OpenApiExample


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
    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]

        return [IsAuthenticated()]

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
        return Order.objects.filter(user=user)

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
                    "order_reference": order.reference,
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

    # 1️⃣ Get Order
    try:
        order = Order.objects.prefetch_related(
            "items__ticket_type").get(reference=reference)

    except Order.DoesNotExist:
        return Response(
            {"error": "Order not found"},
            status=404
        )

    # 2️⃣ Prevent double verification
    if order.status == "paid":
        return Response({
            "message": "Payment already verified",
            "order_id": order.id
        })

    # 3️⃣ Verify payment from Paystack
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

    except requests.RequestException:
        return Response(
            {"error": "Payment verification failed"},
            status=500
        )

    # 4️⃣ Validate Paystack response
    if not paystack_data.get("status"):
        return Response(
            {"error": "Invalid Paystack response"},
            status=400
        )

    payment_data = paystack_data["data"]

    if payment_data["status"] != "success":
        return Response(
            {"error": "Payment not successful"},
            status=400
        )

    # Security: Validate amount
    expected_amount = int(order.total_amount * 100)

    if payment_data["amount"] != expected_amount:
        return Response(
            {"error": "Payment amount mismatch"},
            status=400
        )

    # 6️Atomic transaction
    with transaction.atomic():

        # Lock ticket rows to prevent overselling
        order_items = order.items.select_related(
            "ticket_type"
        ).select_for_update()

        for item in order_items:

            ticket_type = item.ticket_type

            if ticket_type.remaining < item.quantity:
                return Response(
                    {
                        "error":
                        f"Insufficient tickets for {ticket_type.name}"
                    },
                    status=400,
                )

            # Reduce stock
            ticket_type.remaining -= item.quantity
            ticket_type.save(update_fields=["remaining"])

        # Update order
        order.status = "paid"
        order.verified_at = timezone.now()
        order.save(update_fields=["status", "verified_at"])

        tickets = generate_tickets(order)

        # Prepare ticket data for the frontend
        ticket_data = [{
            "ticket_code": t.ticket_code,
            "qr_code_url": request.build_absolute_uri(t.qr_image.url),
            "ticket_type": t.ticket_type.name
        } for t in tickets]

    return Response({
        "message": "Payment verified successfully",
        "order_reference": order.reference,
        "tickets": ticket_data
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
    from_email = settings.EMAIL_HOST_USER
    recipient_list = [order.user.email]

    text_content = f"""
Hi,

Your payment was successful.

Order Reference: {order.reference}
Tickets: {tickets.count()}

Please view this email in HTML to see your QR codes.
"""

    qr_html_blocks = ""
    for i, ticket in enumerate(tickets):
        qr_html_blocks += f"""
        <div style="margin-bottom:20px;">
            <p><strong>Ticket #{i + 1}</strong></p>
            <img src="cid:qr_{i}" width="200" />
        </div>
        """

    html_content = f"""
    <html>
        <body style="font-family: Arial; background:#f4f4f4; padding:20px;">
            <div style="max-width:600px; margin:auto; background:white; padding:20px; border-radius:10px;">
                <h2 style="color:#333;">Payment Successful!</h2>
                <p>Your ticket has been confirmed.</p>
                <p><strong>Order Ref:</strong> {order.reference}</p>
                <p><strong>Total Tickets:</strong> {tickets.count()}</p>

                <hr />

                <h3>Your QR Tickets</h3>
                {qr_html_blocks}

                <hr />

                <p style="font-size:12px; color:gray;">
                    Please present this QR code at the event entrance.
                </p>

                <p><strong>Event:</strong> {order.event.title}</p>
                <p><strong>Date:</strong> {order.event.start_date}</p>
                <p><strong>Location:</strong> {order.event.city}</p>
            </div>
        </body>
    </html>
    """

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
            
            image = MIMEImage(image_data, _subtype="png")
            image.add_header("Content-ID", f"<qr_{i}>")
            image.add_header(
                "Content-Disposition",
                "inline",
                filename=f"{ticket.ticket_code}.png",
            )
            msg.attach(image)
    try:
        msg.mixed_subtype = "related"
        msg.send(fail_silently=False)
        print("email sent!")
    except Exception as e:
        print(f"Error: {e}")
