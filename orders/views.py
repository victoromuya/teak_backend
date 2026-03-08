import requests
from django.conf import settings
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
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

from django.core.mail import EmailMessage
from django.template.loader import render_to_string


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
        try:
            order = Order.objects.select_for_update().get(reference=reference)
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=404)

        if order.status == "paid":
            return Response({"message": "Order already verified"})

        url = f"https://api.paystack.co/transaction/verify/{reference}"

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        }

        response = requests.get(url, headers=headers)
        data = response.json()

        if not data.get("status"):
            return Response({"error": "Payment verification failed"}, status=400)

        payment_data = data["data"]

        if payment_data["status"] != "success":
            order.status = "failed"
            order.save()
            return Response({"error": "Payment not successful"}, status=400)

        # Atomic stock update
        with transaction.atomic():
            for item in order.items.select_related("ticket_type"):
                ticket = item.ticket_type

                if ticket.remaining < item.quantity:
                    return Response(
                        {"error": f"Not enough stock for {ticket.name}"},
                        status=400,
                    )

                ticket.remaining -= item.quantity
                ticket.save()

            order.status = "paid"
            order.save()

        return Response({
            "message": "Payment verified successfully",
            "order_id": order.id,
            "status": order.status,
        })


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

    # 5️⃣ Security: Validate amount
    expected_amount = int(order.total_amount * 100)

    if payment_data["amount"] != expected_amount:
        return Response(
            {"error": "Payment amount mismatch"},
            status=400
        )

    # 6️⃣ Atomic transaction
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

        # Send confirmation email
      
        send_ticket_email(order)

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


def send_ticket_email(order):
    tickets = order.ticket_set.all()

    subject = "Your Ticket Confirmation"
    body = f"""
    Hi,

    Your payment was successful.

    Order Reference: {order.reference}
    Number of Tickets: {tickets.count()}

    Your QR tickets are attached.
    """

    email = EmailMessage(
        subject,
        body,
        settings.EMAIL_HOST_USER,
        [order.user.email],   # assuming order has email field
    )

    for ticket in tickets:
        email.attach_file(ticket.qr_image.path)

    print(ticket.qr_image.path)
    print("mail sent")

    email.send()