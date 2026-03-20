from django.urls import path

from .views import RegisterView, UserProfileView, OrganizerProfileView, \
    PasswordResetRequestView, PasswordResetConfirmView, \
        VerifyEmailView, EmailVerificationRequestView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenBlacklistView,
)


urlpatterns = [
    path('register/', RegisterView.as_view()),
    path('login/', TokenObtainPairView.as_view()),
    path('refresh/', TokenRefreshView.as_view()),
    path('api/logout/', TokenBlacklistView.as_view(), name='token_blacklist'),
    path("organizer/profile/", OrganizerProfileView.as_view()),
    path("user/profile/", UserProfileView.as_view()),

    path("password-reset/request/", PasswordResetRequestView.as_view()),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view()),
    path("email-verification/", EmailVerificationRequestView.as_view()),
    path("verify-email/", VerifyEmailView.as_view()),

    # path("admin/users/", AdminUsersView.as_view()),
    
    # path("admin/events/", AdminEventsView.as_view()),
    # path("admin/orders/", AdminOrdersView.as_view()),
]

