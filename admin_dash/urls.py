from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminAuthMeView,
    AdminDashboardView,
    AdminEventViewSet,
    AdminLoginView,
    AdminOrderViewSet,
    AdminTicketTypeViewSet,
    AdminTicketViewSet,
    AdminUserViewSet,
)


router = DefaultRouter()

router.register("users", AdminUserViewSet)
router.register("events", AdminEventViewSet)
router.register("orders", AdminOrderViewSet)
router.register("tickets", AdminTicketViewSet)
router.register("ticketype", AdminTicketTypeViewSet)

urlpatterns = router.urls

urlpatterns += [
    path("auth/login/", AdminLoginView.as_view()),
    path("auth/me/", AdminAuthMeView.as_view()),
    path("dashboard/", AdminDashboardView.as_view()),
]
