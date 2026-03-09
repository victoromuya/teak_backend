# events/views.py

from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from .permissions import CanDeleteEvent, IsOrganizer, IsOrganizerOrAdmin
from .models import Event, TicketType
from .serializers import EventSerializer, TicketTypeSerializer
from drf_spectacular.utils import extend_schema

@extend_schema(
    tags=["Events"],
    description="List all events"
)
class EventViewSet(ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    # 🔐 Only restrict UPDATE & DELETE
    def get_permissions(self):
        # Anyone can view
        if self.action == "create":
            return [IsOrganizerOrAdmin()]

        if self.action in ["update", "partial_update", "destroy"]:
            return [IsAuthenticated(), CanDeleteEvent()]

        return []  # No permissions required for read
        # return [IsAuthenticatedOrReadOnly()]

        # 🔹 CREATE event
        if self.action == "create":
            return [IsOrganizerOrAdmin()]

    

    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user)

    def get_queryset(self):
        user = self.request.user

        # Admin sees all
        if user.is_staff:
            return Event.objects.all()

        # Organizer sees only their events
        if user.is_authenticated and user.is_organizer:
            return Event.objects.filter(organizer=user)

        # Public users see only active events
        return Event.objects.filter(is_active=True)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        if not user.is_authenticated or not user.is_staff:
            if not obj.is_active:
                raise Http404("Event not found")
        return obj


class TicketTypeViewSet(ModelViewSet):

    queryset = TicketType.objects.all()
    serializer_class = TicketTypeSerializer
    permission_classes = [IsAuthenticated, IsOrganizer]

    # def get_queryset(self):
    #     return TicketType.objects.filter(
    #         event__organizer=self.request.user
    #     )

    # def perform_create(self, serializer):
    #     event_id = self.kwargs.get('event_id')
    #     event = Event.objects.get(id=event_id)

    #     if event.organizer != self.request.user:
    #         raise PermissionDenied("Not your event")

    #     serializer.save(event=event)