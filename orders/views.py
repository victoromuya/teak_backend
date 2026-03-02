import requests
from django.conf import settings
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Order
from .serializers import OrderCreateSerializer

from django.db import transaction
from rest_framework.decorators import action

from rest_framework import status


class OrderViewSet(ModelViewSet):
    queryset = Order.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return OrderCreateSerializer

    def get_queryset(self):
        user = self.request.user
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


@action(detail=False, methods=["get"], url_path="verify/(?P<reference>[^/.]+)")
def verify_payment(self, request, reference=None):
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

    # ✅ Atomic stock update
    with transaction.atomic():
        for item in order.items.select_related("ticket_type"):
            ticket = item.ticket_type

            if ticket.stock < item.quantity:
                return Response(
                    {"error": f"Not enough stock for {ticket.name}"},
                    status=400,
                )

            ticket.stock -= item.quantity
            ticket.save()

        order.status = "paid"
        order.save()

    return Response({
        "message": "Payment verified successfully",
        "order_id": order.id,
        "status": order.status,
    })