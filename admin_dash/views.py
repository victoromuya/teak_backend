from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.viewsets import ModelViewSet

from accounts.serializers import UserSerializer
from events.serializers import EventSerializer, TicketTypeSerializer
from orders.serializers import OrderSerializer, TicketSerializer
from events.models import Event, TicketType
from orders.models import Order, Ticket
from accounts.permissions import IsAdmin, IsOrganizer, IsNormalUser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count

from django.utils import timezone
from datetime import timedelta
from drf_spectacular.utils import extend_schema
from django.contrib.auth import get_user_model

User = get_user_model()



class AdminUserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsAdmin]


class AdminEventViewSet(ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated, IsAdmin]

class AdminOrderViewSet(ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated, IsAdmin]

class AdminTicketViewSet(ModelViewSet):
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated, IsAdmin]

class AdminTicketTypeViewSet(ModelViewSet):
    queryset = TicketType.objects.all()
    serializer_class = TicketTypeSerializer
    permission_classes = [IsAuthenticated, IsAdmin]


@extend_schema(tags=["Admin"], description="Admin dashboard analytics")
class AdminDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):

        # Basic counts
        total_users = User.objects.count()
        total_organizers = User.objects.filter(is_organizer=True).count()
        total_events = Event.objects.count()
        total_orders = Order.objects.count()

        # Revenue
        total_revenue = Order.objects.aggregate(
            total=Sum("total_amount")
        )["total"] or 0

        # Recent Orders
        recent_orders = (
            Order.objects.select_related("user", "event")
            .order_by("-created_at")[:5]
            .values(
                "id",
                "user__username",
                "event__title",
                "total_amount",
                "created_at"
            )
        )

        # Recent Events
        recent_events = (
            Event.objects.order_by("-created_at")[:5]
            .values("id", "title", "date", "location")
        )

        # Top events by ticket sales
        top_events = (
            Order.objects.values("event__title")
            .annotate(total_sales=Count("id"))
            .order_by("-total_sales")[:5]
        )

        # Orders in the last 7 days
        last_7_days = timezone.now() - timedelta(days=7)

        weekly_orders = (
            Order.objects.filter(created_at__gte=last_7_days)
            .extra(select={'day': "date(created_at)"})
            .values("day")
            .annotate(total=Count("id"))
            .order_by("day")
        )

        data = {
            "stats": {
                "total_users": total_users,
                "total_organizers": total_organizers,
                "total_events": total_events,
                "total_orders": total_orders,
                "total_revenue": total_revenue,
            },

            "recent_orders": list(recent_orders),
            "recent_events": list(recent_events),
            "top_events": list(top_events),
            "weekly_orders": list(weekly_orders),
        }

        return Response(data)