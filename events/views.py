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

@extend_schema(
    tags=["Events"],
    description="List all events"
)
class EventViewSet(ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    # Only restrict UPDATE & DELETE
    def get_permissions(self):
        # Anyone can view
        if self.action == "create":
            return [IsOrganizerOrAdmin()]

        if self.action in ["update", "partial_update", "destroy"]:
            return [IsAuthenticated(), CanDeleteEvent()]

        return []  # No permissions required for read
        # return [IsAuthenticatedOrReadOnly()]

        # CREATE event
        # if self.action == "create":
        #     return [IsOrganizerOrAdmin()]



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

    @extend_schema(
        tags=["Events"],
        description="Generate event link"
    )
    @action(detail=True, methods=['get'])
    def link(self, request, pk=None):
        event = self.get_object()
        # Construct frontend URL for event detail
        # Assuming frontend route: /events/{id}
        frontend_url = settings.FRONTEND_URL.rstrip('/') if settings.FRONTEND_URL else ''
        event_link = f"{frontend_url}/event/{event.id}"
        return Response({'event_link': event_link})

    @extend_schema(
        tags=["Events"],
        description="List events created by the logged-in user"
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_events(self, request):
        user = request.user
        # Filter events where the user is the organizer
        queryset = Event.objects.filter(organizer=user)
        # Optionally, we can also filter by is_active? The requirement didn't specify.
        # We'll return all events created by the user regardless of active status.
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


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
