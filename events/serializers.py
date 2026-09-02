# events/serializers.py
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone
from .models import TicketType, Event
from orders.models import Ticket
# events/serializers.py

class EventSerializer(serializers.ModelSerializer):
    ticket_prices = serializers.SerializerMethodField(read_only=True)
    free_ticket_quantity = serializers.IntegerField(
        write_only=True,
        required=False,
        min_value=1,
    )

    class Meta:
        model = Event
        fields = '__all__'
        read_only_fields = ['organizer', 'created_at', 'is_deleted']
        start_time = serializers.TimeField(format='%H:%M', input_formats=['%I:%M %p', '%H:%M'])
        end_time = serializers.TimeField(format='%H:%M', input_formats=['%I:%M %p', '%H:%M'])

    def get_ticket_prices(self, event):
        """Return the public pricing information needed by event listing cards."""
        tickets = sorted(
            event.ticket_types.all(),
            key=lambda ticket: (ticket.price, ticket.id),
        )
        return [
            {"name": ticket.name, "price": ticket.price}
            for ticket in tickets
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)

        request = self.context.get("request")
        if "is_featured" in attrs and not (
            request and request.user.is_authenticated and request.user.is_staff
        ):
            current_value = (
                self.instance.is_featured if self.instance is not None else False
            )
            if attrs["is_featured"] != current_value:
                raise PermissionDenied(
                    "Only an administrator can change an event's featured status."
                )

            # Some clients submit every form field, including the model default.
            # Do not treat an unchanged value as an attempted admin-only update.
            attrs.pop("is_featured")

        today = timezone.localdate()
        errors = {}

        start_date = attrs.get(
            "start_date",
            getattr(self.instance, "start_date", None),
        )
        if self.instance is None and start_date and start_date < today:
            errors["start_date"] = (
                "Please choose today or a future date for the event start date."
            )

        end_date = attrs.get(
            "end_date",
            getattr(self.instance, "end_date", None),
        )
        if self.instance is None and end_date and end_date < today:
            errors["end_date"] = (
                "Please choose today or a future date for the event end date."
            )

        if start_date and end_date and end_date < start_date:
            errors["end_date"] = (
                "Please choose an event end date that is the same as or later "
                "than the start date."
            )

        if errors:
            if start_date and end_date and end_date < start_date:
                errors["message"] = (
                    "The event end date cannot be earlier than the start date."
                )
            else:
                errors["message"] = "Events cannot be created using past dates."
            raise serializers.ValidationError(errors)

        return attrs

    def create(self, validated_data):
        free_quantity = validated_data.pop("free_ticket_quantity", 100)
        event = super().create(validated_data)
        self._ensure_free_ticket(event, free_quantity)
        return event

    def update(self, instance, validated_data):
        free_quantity = validated_data.pop("free_ticket_quantity", 100)
        event = super().update(instance, validated_data)
        self._ensure_free_ticket(event, free_quantity)
        return event

    @staticmethod
    def _ensure_free_ticket(event, quantity):
        if event.paid_event:
            return
        if event.ticket_types.filter(price=0).exists():
            return
        TicketType.objects.create(
            event=event,
            name="Free Entry",
            price=0,
            quantity=quantity,
            remaining=quantity,
        )


class ContactOrganizerSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200, trim_whitespace=True)
    message = serializers.CharField(max_length=5000, trim_whitespace=True)

    def validate_subject(self, value):
        if "\n" in value or "\r" in value:
            raise serializers.ValidationError(
                "The subject must not contain line breaks."
            )
        return value


class TicketTypeSerializer(serializers.ModelSerializer):
    event = serializers.PrimaryKeyRelatedField(
        queryset=Event.objects.filter(is_deleted=False)
    )

    class Meta:
        model = TicketType
        fields = "__all__"
        read_only_fields = ['remaining', 'created_at', "organizer"]

    def validate_event(self, value):
        request = self.context["request"]

        # Admin can assign to any event
        if request.user.is_staff:
            return value

        # Organizer can attach only to their own events
        if hasattr(request.user, 'is_organizer') and request.user.is_organizer:
            if value.organizer != request.user:
                raise serializers.ValidationError(
                    "You can only create tickets for your own events."
                )
            return value

        # All other users cannot attach tickets
        raise serializers.ValidationError("You do not have permission to add tickets.")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        event = attrs.get("event", getattr(self.instance, "event", None))
        sales_expiry_date = attrs.get(
            "sales_expiry_date",
            getattr(self.instance, "sales_expiry_date", None),
        )

        if event is None or sales_expiry_date is None:
            return attrs

        if timezone.is_aware(sales_expiry_date):
            sales_expiry_day = timezone.localtime(sales_expiry_date).date()
        else:
            sales_expiry_day = sales_expiry_date.date()

        if event.end_date and sales_expiry_day > event.end_date:
            message = (
                f"Please choose a ticket sales expiry date on or before "
                f"{event.end_date:%B %d, %Y}. This is the event end date."
            )
            raise serializers.ValidationError({
                "sales_expiry_date": message,
                "message": message,
            })

        return attrs

    def create(self, validated_data):
        validated_data['remaining'] = validated_data['quantity']
        return super().create(validated_data)



class SoldTicketSerializer(serializers.ModelSerializer):
    attendee = serializers.SerializerMethodField()
    email = serializers.EmailField(source="order.user.email", read_only=True)
    ticket_type = serializers.CharField(source="ticket_type.name", read_only=True)
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    payment_status = serializers.CharField(source="order.status", read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_code",
            "ticket_type",
            "attendee",
            "email",
            "order_reference",
            "payment_status",
            "is_used",
            "scanned_at",
            "created_at",
        ]

    
    def get_attendee(self, obj):
        return obj.order.user.get_full_name() or obj.order.user.email
