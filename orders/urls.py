from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, WithdrawalRequestViewSet, verify_payment, payment_success, platform_config
from .webhook import paystack_webhook


router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'withdrawals', WithdrawalRequestViewSet, basename='withdrawals')

# urlpatterns = router.urls + [
#     path("payments/webhook/", paystack_webhook),
# ]

urlpatterns = [
    path("", include(router.urls)),
    path("platform-config/", platform_config, name="platform_config"),
    path("orders/verify/<str:reference>/", verify_payment, name="verify_payment"),
    path("payment-success/", payment_success, name="payment_success"),
    path("payments/webhook/", paystack_webhook),
]
