from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.views import TokenRefreshView

from .throttles import AuthThrottle


class RevokingTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = self.token_class(attrs["refresh"])
        user_id = token.get(api_settings.USER_ID_CLAIM)
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
            if user is None:
                raise InvalidToken("Invalid refresh token.")
            # Password changes revoke refresh tokens as well as access tokens.
            JWTAuthentication().get_user(token)
            # Revalidate blacklist after taking the lock to prevent parallel reuse.
            return super().validate(attrs)


class SecureTokenRefreshView(TokenRefreshView):
    serializer_class = RevokingTokenRefreshSerializer
    throttle_classes = [AuthThrottle]
    auth_limit_group = "refresh"
