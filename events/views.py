# events/views.py

from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.db.models import Q
from glob_utils.send_email import send_email
from .permissions import CanDeleteEvent, IsOrganizer, IsOrganizerOrAdmin, CanManageTicketType
from .models import Event, TicketType
from .serializers import (
    ContactOrganizerSerializer,
    EventSerializer,
    TicketTypeSerializer,
    SoldTicketSerializer,
)
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
    queryset = Event.objects.filter(is_deleted=False)
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        today = timezone.localdate()
        Event.objects.filter(
            is_active=True,
            is_deleted=False,
            end_date__lt=today,
        ).update(is_active=False)
        # Keep newly published events visible near the top of public listings.
        # Without an explicit order, database row order is undefined and new
        # events could appear at the end of the homepage's event collection.
        queryset = Event.objects.filter(is_deleted=False).order_by("-created_at", "-id")

        upcoming_events = Q(is_active=True) & (
            Q(end_date__gte=today)
            | Q(end_date__isnull=True, start_date__gte=today)
        )

        # The general list powers public pages such as the homepage. Keep its
        # visibility rules identical for anonymous and authenticated visitors;
        # organizers use the dedicated my_events action for drafts and history.
        if self.action == "list":
            return queryset.filter(upcoming_events)

        # Admins retain unrestricted access through detail and management
        # actions, while the public list above remains public-safe.
        if user.is_authenticated and user.is_staff:
            return queryset

        # Organizers retain access to all events they created, including past
        # and inactive events through detail/management actions.
        if user.is_authenticated and getattr(user, "is_organizer", False):
            return queryset.filter(
                upcoming_events | Q(organizer=user)
            ).distinct()

        return queryset.filter(upcoming_events)


    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user)

    def destroy(self, request, *args, **kwargs):
        event = self.get_object()
        has_orders = event.order_set.exists()

        if (
            not request.user.is_staff
            and has_orders
            and not event.event_date_has_passed()
        ):
            return Response(
                {
                    "detail": (
                        "A published event with orders cannot be deleted until "
                        "the event date has passed."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        if has_orders:
            event.archive()
            return Response(status=status.HTTP_204_NO_CONTENT)

        return super().destroy(request, *args, **kwargs)

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
        event = get_object_or_404(Event, pk=pk)
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
        Event.objects.filter(
            organizer=user,
            is_active=True,
            is_deleted=False,
            end_date__lt=timezone.localdate(),
        ).update(is_active=False)
        # Filter events where the user is the organizer
        queryset = Event.objects.filter(
            organizer=user,
            is_deleted=False,
        ).order_by("-created_at", "-id")
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

    @extend_schema(
        tags=["Events"],
        description=(
            "Send an email to the event organizer. Available to authenticated "
            "users for public events and to users with a paid order for the event."
        ),
        request=ContactOrganizerSerializer,
        responses={200: None},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="contact-organizer",
        permission_classes=[IsAuthenticated],
    )
    def contact_organizer(self, request, pk=None):
        # Do not use get_object() here: paid ticket holders must retain contact
        # access when an event has ended or has subsequently been deactivated.
        event = get_object_or_404(
            Event.objects.select_related("organizer"),
            pk=pk,
            is_deleted=False,
        )

        today = timezone.localdate()
        is_public = event.is_active and (
            (event.end_date is not None and event.end_date >= today)
            or (event.end_date is None and (
                event.start_date is not None and event.start_date >= today
            ))
        )
        has_purchased = event.order_set.filter(
            user=request.user,
            status="paid",
        ).exists()

        if not is_public and not has_purchased:
            raise Http404("Event not found")

        serializer = ContactOrganizerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sender_email = request.user.email
        sender_name = request.user.get_full_name() or sender_email
        body = (
            f"{sender_name} ({sender_email}) sent a message about "
            f'\"{event.title}\".\n\n{serializer.validated_data["message"]}'
        )
        send_email(
            subject=(
                f'[Event enquiry: {event.title}] '
                f'{serializer.validated_data["subject"]}'
            ),
            body=body,
            to_email=event.organizer.email,
            heading="You have a new event enquiry",
            action_label="View event",
            action_url=(
                f'{settings.FRONTEND_URL.rstrip("/")}/event/{event.pk}/event_name'
            ),
            reply_to=[sender_email],
        )

        return Response({"message": "Your message has been sent to the organizer."})
    

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
