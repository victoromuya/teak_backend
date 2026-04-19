import requests
from django.conf import settings
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from glob_utils.send_email import send_email
from .models import Order, OrderItem, Ticket
from .serializers import OrderCreateSerializer, OrderSerializer

from django.db import transaction
from rest_framework.decorators import action, api_view, permission_classes

from rest_framework import status
from django.utils import timezone
from datetime import timedelta

import os
from django.core.files import File
from io import BytesIO
import qrcode

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
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderSerializer

    # def get_serializer_class(self):
    #     return OrderCreateSerializer

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

        # Initialize Paystack
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

        return Response({
            "order_id": order.id,
            "payment_url": data["data"]["authorization_url"],
            "reference": order.reference
        })


    # @action(detail=False, methods=["get"], url_path="verify/(?P<reference>[^/.]+)")
    # def verify_payment(self, request, reference=None):
        # try:
        #     order = Order.objects.select_for_update().get(reference=reference)
        # except Order.DoesNotExist:
        #     return Response({"error": "Order not found"}, status=404)

        # if order.status == "paid":
        #     return Response({"message": "Order already verified"})

        # url = f"https://api.paystack.co/transaction/verify/{reference}"

        # headers = {
        #     "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        # }

        # response = requests.get(url, headers=headers)
        # data = response.json()

        # if not data.get("status"):
        #     return Response({"error": "Payment verification failed"}, status=400)

        # payment_data = data["data"]

        # if payment_data["status"] != "success":
        #     order.status = "failed"
        #     order.save()
        #     return Response({"error": "Payment not successful"}, status=400)

        # # Atomic stock update
        # with transaction.atomic():
        #     for item in order.items.select_related("ticket_type"):
        #         ticket = item.ticket_type

        #         if ticket.remaining < item.quantity:
        #             return Response(
        #                 {"error": f"Not enough stock for {ticket.name}"},
        #                 status=400,
        #             )

        #         ticket.remaining -= item.quantity
        #         ticket.save()

        #     order.status = "paid"
        #     order.save()

        # return Response({
        #     "message": "Payment verified successfully",
        #     "order_id": order.id,
        #     "status": order.status,
        # })




@extend_schema(
    tags=["Orders"],
    description="Verify Payment",
    responses={200: None}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])   # Paystack redirects without auth
def verify_payment(request, reference):

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

        # Generate tickets
        # tickets = []

        # for item in order_items:
        #     for _ in range(item.quantity):

        #         ticket = Ticket.objects.create(
        #             order=order,
        #             ticket_type=item.ticket_type
        #         )

        #         tickets.append(ticket)

        # Generate QR codes
   
        generate_tickets(order)

    return Response({
        "message": "Payment verified successfully",
        "order_reference": order.reference,
        # "tickets_generated": len(tickets)
    })



def generate_tickets(order):

    order_items = OrderItem.objects.filter(order=order)

    for item in order_items:

        ticket_type = item.ticket_type
        quantity = item.quantity

        for i in range(quantity):

            ticket = Ticket.objects.create(
                order=order,
                ticket_type=ticket_type
            )

            qr = qrcode.make(str(ticket.ticket_code))

            buffer = BytesIO()
            qr.save(buffer, format="PNG")

            filename = f"{ticket.ticket_code}.png"
            ticket.qr_image.save(filename, File(buffer), save=True)

    send_ticket_email(order)


def _legacy_send_ticket_email_unused(order):
    return None
    '''
    tickets = order.ticket_set.all()

    msg = EmailMessage()
    msg["Subject"] = "🎟️ Your Ticket Confirmation"
    msg["From"] = settings.EMAIL_HOST_USER
    msg["To"] = order.user.email

    # Plain fallback (for email clients that don’t support HTML)
    msg.set_content(f"""
Hi,

Your payment was successful.

Order Reference: {order.reference}
Tickets: {tickets.count()}

Please view this email in HTML to see your QR codes.
""")

    # 🔥 Build HTML content dynamically
    qr_html_blocks = ""

    for i, ticket in enumerate(tickets):
        qr_html_blocks += f"""
        <div style="margin-bottom:20px;">
            <p><strong>Ticket #{i+1}</strong></p>
            <img src="cid:qr_{i}" width="200" />
        </div>
        """

    html_content = f"""
    <html>
        <body style="font-family: Arial; background:#f4f4f4; padding:20px;">
            <div style="max-width:600px; margin:auto; background:white; padding:20px; border-radius:10px;">
                
                <h2 style="color:#333;">🎉 Payment Successful!</h2>
                
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

    # Attach HTML version
    msg.add_alternative(html_content, subtype="html")

    # ✅ Attach QR images inline
    for i, ticket in enumerate(tickets):
        if ticket.qr_image:
            with open(ticket.qr_image.path, "rb") as f:
                msg.get_payload()[1].add_related(
                    f.read(),
                    maintype="image",
                    subtype="png",
                    cid=f"qr_{i}"
                )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(msg)

        print("email sent!")

    except Exception as e:
        print(f"Error: {e}")
    '''


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
            with open(ticket.qr_image.path, "rb") as f:
                image = MIMEImage(f.read(), _subtype="png")
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
