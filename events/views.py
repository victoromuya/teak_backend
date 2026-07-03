# events/views.py

from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import Http404
from django.conf import settings
from .permissions import CanDeleteEvent, IsOrganizer, IsOrganizerOrAdmin
from .models import Event, TicketType
from .serializers import EventSerializer, TicketTypeSerializer
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

@extend_schema(
    tags=["Events"],
    description="Manage events",
    parameters=[
        OpenApiParameter(
            name="mine",
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            description="If true, returns only events created by the authenticated user."
        )
    ]
)
class EventViewSet(ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):
        # Create
        if self.action == "create":
            return [IsOrganizerOrAdmin()]

        # Update/Delete
        if self.action in ["update", "partial_update", "destroy"]:
            return [IsAuthenticated(), CanDeleteEvent()]

        # Read
        return []

    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user)

    def get_queryset(self):
        user = self.request.user
        queryset = Event.objects.all()

        # Admin sees everything
        if user.is_staff:
            return queryset

        # Logged-in organizer requesting only their events
        if (
            user.is_authenticated
            and self.request.query_params.get("mine") == "true"
        ):
            return queryset.filter(organizer=user)

        # Organizer (default)
        if user.is_authenticated and user.is_organizer:
            return queryset.filter(is_active=True)

        # Public users
        return queryset.filter(is_active=True)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        # Admin can access everything
        if user.is_staff:
            return obj

        # Organizer can access their own events (active or inactive)
        if user.is_authenticated and obj.organizer == user:
            return obj

        # Public cannot access inactive events
        if not obj.is_active:
            raise Http404("Event not found")

        return obj

    @extend_schema(
        tags=["Events"],
        description="Generate event link"
    )
    @action(detail=True, methods=["get"])
    def link(self, request, pk=None):
        event = self.get_object()

        frontend_url = (
            settings.FRONTEND_URL.rstrip("/")
            if settings.FRONTEND_URL
            else ""
        )

        event_link = f"{frontend_url}/event/{event.id}"

        return Response({"event_link": event_link})

@extend_schema(
    tags=["Events"],
    description="List all ticket types"
)
class TicketTypeViewSet(ModelViewSet):

    queryset = TicketType.objects.all()
    serializer_class = TicketTypeSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):
        # Anyone can view
        if self.action == "create":
            return [IsOrganizerOrAdmin()]

        if self.action in ["update", "partial_update", "destroy"]:
            return [IsAuthenticated(), CanDeleteEvent()]

        return []

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
