from rest_framework import serializers
from django.db import transaction
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

            for item in items_data:
                ticket = ticket_map[item["ticket_type"]]

                if item["quantity"] > ticket.quantity:
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