from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, verify_payment
from .webhook import paystack_webhook


router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='orders')

# urlpatterns = router.urls + [
#     path("payments/webhook/", paystack_webhook),
# ]

urlpatterns = [
    path("", include(router.urls)),
    path("orders/verify/<str:reference>/", verify_payment, name="verify_payment"),
    path("payments/webhook/", paystack_webhook),
]