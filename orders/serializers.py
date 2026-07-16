from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from events.models import TicketType
from events.serializers import EventSerializer
from .models import Order, OrderItem, Ticket
import uuid



class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = "__all__"

class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = "__all__"


class PurchasedTicketSerializer(serializers.ModelSerializer):
    ticket_type = serializers.CharField(source="ticket_type.name", read_only=True)
    price = serializers.DecimalField(
        source="ticket_type.price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    event = EventSerializer(source="order.event", read_only=True)
    qr_code_url = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_code",
            "ticket_type",
            "price",
            "order_reference",
            "event",
            "qr_code_url",
            "is_used",
            "scanned_at",
            "created_at",
        ]

    def get_qr_code_url(self, obj):
        if not obj.qr_image:
            return None

        request = self.context.get("request")
        url = obj.qr_image.url
        return request.build_absolute_uri(url) if request else url

class OrderItemInputSerializer(serializers.Serializer):
    ticket_type = serializers.IntegerField()
    quantity = serializers.IntegerField()


class OrderCreateSerializer(serializers.Serializer):
    event = serializers.IntegerField()
    items = OrderItemInputSerializer(many=True)

    def validate(self, data):
        if not data["items"]:
            raise serializers.ValidationError("Order must contain at least one ticket.")
        return data

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user

        items_data = validated_data["items"]
        total_amount = 0

        with transaction.atomic():
            # Lock selected ticket rows
            ticket_ids = [item["ticket_type"] for item in items_data]
            tickets = TicketType.objects.select_for_update().filter(id__in=ticket_ids)

            ticket_map = {t.id: t for t in tickets}

            if len(ticket_map) != len(ticket_ids):
                raise serializers.ValidationError("Invalid ticket type selected.")

            event_id = validated_data["event"]
            if any(ticket.event_id != event_id for ticket in tickets):
                raise serializers.ValidationError(
                    {
                        "items": (
                            "All selected ticket types must belong to the "
                            "event being ordered."
                        )
                    }
                )

            now = timezone.now()
            for item in items_data:
                ticket = ticket_map[item["ticket_type"]]

                if (
                    ticket.sales_expiry_date is not None
                    and now >= ticket.sales_expiry_date
                ):
                    message = (
                        f"{ticket.name} tickets are no longer available for "
                        "sale because the sales period has ended."
                    )
                    raise serializers.ValidationError({
                        "items": message,
                        "message": message,
                    })

                if item["quantity"] > ticket.remaining:
                    raise serializers.ValidationError(
                        f"Not enough stock for {ticket.name}"
                    )

                total_amount += ticket.price * item["quantity"]

            reference = str(uuid.uuid4())

            order = Order.objects.create(
                user=user,
                event_id=validated_data["event"],
                reference=reference,
                total_amount=total_amount,
                status="pending",
            )

            for item in items_data:
                ticket = ticket_map[item["ticket_type"]]

                OrderItem.objects.create(
                    order=order,
                    ticket_type=ticket,
                    quantity=item["quantity"],
                    price=ticket.price,
                )

            return order
        


class TicketScanSerializer(serializers.Serializer):
    ticket_code = serializers.UUIDField()
