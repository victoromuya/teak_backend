from django.urls import path

from .views import AdminDashboardView, AdminUserViewSet, AdminEventViewSet,\
    AdminTicketViewSet, AdminOrderViewSet, AdminTicketTypeViewSet

from rest_framework.routers import DefaultRouter


router = DefaultRouter()

router.register("users", AdminUserViewSet)
router.register("events", AdminEventViewSet)
router.register("orders", AdminOrderViewSet)
router.register("tickets", AdminTicketViewSet)
router.register("ticketype", AdminTicketTypeViewSet)

urlpatterns = router.urls

urlpatterns += [
    path("dashboard/", AdminDashboardView.as_view()),
]
