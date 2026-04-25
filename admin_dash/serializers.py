from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()


class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        try:
            User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "No account found with this email address."}
            )

        authenticated_user = authenticate(email=email, password=password)
        if authenticated_user is None:
            raise serializers.ValidationError(
                {"password": "The password you entered is incorrect."}
            )

        if not authenticated_user.is_active:
            raise serializers.ValidationError({"detail": "This account is inactive."})

        if not authenticated_user.is_staff:
            raise serializers.ValidationError(
                {"detail": "You do not have admin access."}
            )

        refresh = RefreshToken.for_user(authenticated_user)

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": authenticated_user.id,
                "email": authenticated_user.email,
                "first_name": authenticated_user.first_name,
                "last_name": authenticated_user.last_name,
                "is_staff": authenticated_user.is_staff,
                "is_superuser": authenticated_user.is_superuser,
            },
        }
