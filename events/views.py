# events/views.py

from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import Http404
from django.conf import settings
from .permissions import CanDeleteEvent, IsOrganizer, IsOrganizerOrAdmin, CanManageTicketType
from .models import Event, TicketType
from .serializers import EventSerializer, TicketTypeSerializer, SoldTicketSerializer
from drf_spectacular.utils import extend_schema

from rest_framework import status

from orders.models import Ticket
from orders.serializers import TicketScanSerializer
from orders.permissions import CanScanTicket
from django.utils import timezone

@extend_schema(
    tags=["Events"],
    description="List all events"
)
class EventViewSet(ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user

        queryset = Event.objects.all()

        # Admin sees everything
        if user.is_authenticated and user.is_staff:
            return queryset

        # Everyone else (public and logged-in users)
        # sees all active events
        return queryset.filter(is_active=True)


    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user)

    def get_permissions(self):

        if self.action == "create":
            return [IsOrganizerOrAdmin()]

        if self.action in ["update", "partial_update", "destroy"]:
            return [IsAuthenticated(), CanDeleteEvent()]

        return super().get_permissions()


    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        # Admin can access everything
        if user.is_staff:
            return obj

        # Organizer can access their own events (active or inactive)
        if user.is_authenticated and obj.organizer == user:
            return obj

        # Everyone else can only access active events
        if not obj.is_active:
            raise Http404("Event not found")

        return obj
    
    # ===================================
    # SEE ALL SOLD TICKETS FOR AN EVENT
    # ==================================
    @action(
    detail=True,
    methods=["get"],
    url_path="sold-tickets",
    permission_classes=[CanScanTicket],
)
    def sold_tickets(self, request, pk=None):
        event = self.get_object()
        self.check_object_permissions(request, event)

        tickets = Ticket.objects.filter(
            order__event=event,
            order__status="paid"
        ).select_related(
            "order__user",
            "ticket_type"
        )

        serializer = SoldTicketSerializer(tickets, many=True)
        return Response(serializer.data)


    # ===================================
    # GENERATE EVENT LINK
    # ==================================
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

    # ===================================
    # MY EVENTS 
    # ===================================
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
    
     # ===================================
    # LIST ALL TICKET TYPES FOR AN EVENT
    # ==================================
    @extend_schema(
        tags=["Events"],
        description="List all ticket types for a specific event",
        responses=TicketTypeSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        event = self.get_object()
        queryset = TicketType.objects.filter(event=event)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = TicketTypeSerializer(page, many=True)
            return self.get_paginated_response(serializer)

        serializer = TicketTypeSerializer(queryset, many=True)
        return Response(serializer.data)
    

 # ===================================
    # SCAN A TICKET FOR AN EVENT
    # ==================================

    @extend_schema(
    tags=["Events"],
    description="Scan a ticket for this event",
    request=TicketScanSerializer,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="scan-ticket",
        permission_classes=[CanScanTicket],
    )
    def scan_ticket(self, request, pk=None):

        event = self.get_object()

        # First, ensure the user owns this event (unless admin)
        if not request.user.is_staff and event.organizer != request.user:
            return Response(
                {
                    "success": False,
                    "message": "You are not authorized to scan tickets for this event."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = TicketScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket_code = serializer.validated_data["ticket_code"]

        try:
            ticket = Ticket.objects.select_related(
                "order",
                "order__user",
                "ticket_type"
            ).get(ticket_code=ticket_code)

        except Ticket.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Ticket not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # Ensure the ticket belongs to this event
        if ticket.order.event != event:
            return Response(
                {
                    "success": False,
                    "message": "This ticket does not belong to this event."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Ensure payment is completed
        if ticket.order.status != "paid":
            return Response(
                {
                    "success": False,
                    "message": "This ticket has not been paid for."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Ensure ticket hasn't already been used
        if ticket.is_used:
            return Response(
                {
                    "success": False,
                    "message": "Ticket has already been scanned."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        ticket.is_used = True
        ticket.scanned_at = timezone.now()
        ticket.scanned_by = request.user
        ticket.save()

        return Response(
            {
                "success": True,
                "message": "Ticket verified successfully.",
                "ticket": {
                    "ticket_code": str(ticket.ticket_code),
                    "attendee": ticket.order.user.get_full_name(),
                    "email": ticket.order.user.email,
                    "ticket_type": ticket.ticket_type.name,
                    "scanned_at": ticket.scanned_at,
                }
            }
        )


@extend_schema(
    tags=["Events"],
    description="List all ticket types"
)
class TicketTypeViewSet(ModelViewSet):

    queryset = TicketType.objects.all()
    serializer_class = TicketTypeSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):

        if self.action == "create":
            return [IsOrganizerOrAdmin()]

        if self.action in ["update", "partial_update", "destroy"]:
            return [IsAuthenticated(), CanManageTicketType()]

        return super().get_permissions()




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
