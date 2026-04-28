from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import IsAdmin
from accounts.serializers import UserSerializer
from events.models import Event, TicketType
from events.serializers import EventSerializer, TicketTypeSerializer
from orders.models import Order, Ticket
from orders.serializers import OrderSerializer, TicketSerializer

from .serializers import AdminLoginSerializer


User = get_user_model()


@extend_schema(
    tags=["admin auth"],
    description="Authenticate an admin user and return JWT tokens",
    request=AdminLoginSerializer,
)
class AdminLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


@extend_schema(tags=["admin auth"], description="Get the currently authenticated admin")
class AdminAuthMeView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        return Response(
            {
                "user": {
                    "id": request.user.id,
                    "email": request.user.email,
                    "first_name": request.user.first_name,
                    "last_name": request.user.last_name,
                    "is_staff": request.user.is_staff,
                    "is_superuser": request.user.is_superuser,
                }
            }
        )


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


@extend_schema(tags=["admin"], description="Admin dashboard analytics")
class AdminDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        total_users = User.objects.count()
        total_organizers = User.objects.filter(is_organizer=True).count()
        total_events = Event.objects.count()
        total_orders = Order.objects.count()

        total_revenue = Order.objects.aggregate(total=Sum("total_amount"))["total"] or 0

        recent_orders = (
            Order.objects.select_related("user", "event")
            .order_by("-created_at")[:5]
            .values(
                "id",
                "user__email",
                "event__title",
                "total_amount",
                "created_at",
            )
        )

        recent_events = (
            Event.objects.order_by("-created_at")[:5]
            .values("id", "title", "created_at", "address", "start_date", "end_date")
        )

        top_events = (
            Order.objects.values("event__title")
            .annotate(total_sales=Count("id"))
            .order_by("-total_sales")[:5]
        )

        last_7_days = timezone.now() - timedelta(days=7)
        last_30_days = timezone.now() - timedelta(days=30)

        weekly_orders = (
            Order.objects.filter(created_at__gte=last_7_days)
            .extra(select={"day": "date(created_at)"})
            .values("day")
            .annotate(total=Count("id"))
            .order_by("day")
        )

        monthly_orders = (
            Order.objects.filter(created_at__gte=last_30_days)
            .extra(select={"day": "date(created_at)"})
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
            "monthly_orders": list(monthly_orders),
        }

        return Response(data)
