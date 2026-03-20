# events/serializers.py
from rest_framework import serializers
from .models import TicketType, Event

# events/serializers.py

class EventSerializer(serializers.ModelSerializer):

    class Meta:
        model = Event
        fields = '__all__'
        read_only_fields = ['organizer', 'created_at']
        start_time = serializers.TimeField(format='%H:%M', input_formats=['%I:%M %p', '%H:%M'])
        end_time = serializers.TimeField(format='%H:%M', input_formats=['%I:%M %p', '%H:%M'])

class TicketTypeSerializer(serializers.ModelSerializer):
    event = serializers.PrimaryKeyRelatedField(
        queryset=Event.objects.all()
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

    def create(self, validated_data):
        validated_data['remaining'] = validated_data['quantity']
        return super().create(validated_data)

    