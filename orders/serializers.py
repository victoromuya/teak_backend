from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from events.models import Event, TicketType
from events.serializers import EventSerializer
from .models import Order, OrderItem, Ticket, WithdrawalRequest
from .processing_fees import payment_breakdown
from .limits import MAX_TICKETS_PER_ORDER
import uuid



class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["ticket_type", "quantity", "price"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    tickets_count = serializers.SerializerMethodField()
    event_title = serializers.CharField(source="event.title", read_only=True)

    class Meta:
        model = Order
        fields = "__all__"
        read_only_fields = [
            "id",
            "user",
            "event",
            "reference",
            "total_amount",
            "status",
            "created_at",
            "verified_at",
        ]

    def get_tickets_count(self, obj):
        return sum(item.quantity for item in obj.items.all())

class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = "__all__"


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)
    organizer_name = serializers.SerializerMethodField()
    organizer_email = serializers.EmailField(source="organizer.email", read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = "__all__"
        read_only_fields = [
            "id", "organizer", "email", "gross_revenue", "fee_percentage",
            "fee_amount", "amount", "status", "admin_note", "created_at",
            "completed_at", "completed_by",
        ]

    def get_organizer_name(self, obj):
        return obj.organizer.get_full_name() or obj.organizer.email


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
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_TICKETS_PER_ORDER)


class OrderCreateSerializer(serializers.Serializer):
    event = serializers.IntegerField()
    items = OrderItemInputSerializer(many=True, max_length=MAX_TICKETS_PER_ORDER)

    def validate(self, data):
        if not data["items"]:
            raise serializers.ValidationError("Order must contain at least one ticket.")
        if sum(item["quantity"] for item in data["items"]) > MAX_TICKETS_PER_ORDER:
            message = f"You can book at most {MAX_TICKETS_PER_ORDER} tickets per order."
            raise serializers.ValidationError({"items": message, "message": message})
        return data

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user

        items_data = validated_data["items"]
        total_amount = 0

        with transaction.atomic():
            event_id = validated_data["event"]
            event = Event.objects.select_for_update().filter(pk=event_id).first()
            if event is None or event.is_deleted or not event.is_active:
                message = "This event is not available for booking."
                raise serializers.ValidationError({"event": message, "message": message})
            if event.event_date_has_passed():
                message = "This event has ended and is no longer available for booking."
                raise serializers.ValidationError({"event": message, "message": message})

            # Lock selected ticket rows
            ticket_ids = [item["ticket_type"] for item in items_data]
            tickets = TicketType.objects.select_for_update().filter(id__in=ticket_ids)

            ticket_map = {t.id: t for t in tickets}

            if len(ticket_map) != len(ticket_ids):
                raise serializers.ValidationError("Invalid ticket type selected.")

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

                if not ticket.is_active:
                    message = f"{ticket.name} tickets are no longer available for sale."
                    raise serializers.ValidationError({"items": message, "message": message})

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
            processing_fee, payment_amount = payment_breakdown(total_amount)
            if payment_amount >= 10 ** 10:
                raise serializers.ValidationError("Order total exceeds the supported payment amount.")

            order = Order.objects.create(
                user=user,
                event_id=validated_data["event"],
                reference=reference,
                total_amount=total_amount,
                processing_fee=processing_fee,
                payment_amount=payment_amount,
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
