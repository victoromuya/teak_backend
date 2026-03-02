from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet
from .webhook import paystack_webhook


router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='orders')

urlpatterns = router.urls + [
    path("payments/webhook/", paystack_webhook),
]

