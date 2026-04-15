# accounts/serializers.py

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.mail import send_mail
from django.conf import settings
from .utils.reset_tokens import generate_reset_token
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.password_validation import validate_password
from .utils.reset_tokens import verify_reset_token
from .utils.email_tokens import generate_email_verification_token
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from glob_utils.send_email import send_email

User = get_user_model()

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'password', 'first_name', 'last_name', 'is_organizer']

    
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        role = validated_data.pop("role", "user")

        user = User.objects.create_user(**validated_data)

        if role == "organizer":
            user.is_organizer = True
            user.save()

        return user
       

class LoginSerializer(serializers.Serializer):
    """Serializer for user authentication."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    

    def validate(self, data):
        email = data.get('email')
        password = data.get('password')

        # 1. Validation Logic
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({"email": "No account found with this email address."})

        authenticated_user = authenticate(email=email, password=password)
        if authenticated_user is None:
            raise serializers.ValidationError({"password": "The password you entered is incorrect."})
        
        if not user.is_active:
            raise serializers.ValidationError({"detail": "This account is inactive."})


        # 2. Token Generation
        refresh = RefreshToken.for_user(authenticated_user)

        # 3. Return Tokens + User Data
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': authenticated_user.id,
                'email': authenticated_user.email,
                'first_name': authenticated_user.first_name,
                'last_name': authenticated_user.last_name,
                'is_organizer': authenticated_user.is_organizer,
                'is_email_verified': authenticated_user.is_email_verified,
                'is_active': authenticated_user.is_active,
            }
        }


# class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
#     def validate(self, attrs):
#         try:
#             # This calls the built-in authenticate() logic
#             return super().validate(attrs)
#         except Exception:
#             # Custom error message for invalid email or password
#             raise serializers.ValidationError({
#                 "detail": "We couldn't find an account with that email and password."
#             })
        


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "is_organizer"
        ]



class PasswordResetRequestSerializer(serializers.Serializer):

    email = serializers.EmailField()

    def validate(self, data):

        email = data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return data  # do not reveal if email exists

        token = generate_reset_token(user)
        print(token)

        reset_link = f"{settings.FRONTEND_URL}/api/auth/password-reset/confirm?token={token}"
        print(reset_link)

        # send_mail(
        #     subject="Reset your password",
        #     message=f"Click the link to reset your password: {reset_link}",
        #     from_email=settings.EMAIL_HOST_USER,
        #     recipient_list=[email],
        # )
        
        send_email("Reset your password", 
                   f"Click the link to reset your password: {reset_link}", email)


        return data


class PasswordResetConfirmSerializer(serializers.Serializer):

    token = serializers.CharField()
    new_password = serializers.CharField()

    def validate(self, data):

        user_id = verify_reset_token(data["token"])

        if not user_id:
            raise serializers.ValidationError("Invalid or expired token")

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found")

        validate_password(data["new_password"])

        user.set_password(data["new_password"])
        user.save()

        return data


class EmailVerificationRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate(self, data):
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            return data  # Do not reveal if user exists

        if user.is_email_verified:
            return data

        token = generate_email_verification_token(user)
        
        verification_link = f"{settings.FRONTEND_URL}/api/auth/verify-email?token={token}"
        print(verification_link)
        # Send email
        # send_mail(
        #     subject="Verify your email",
        #     message=f"Click the link to verify your email: {verification_link}",
        #     from_email=settings.EMAIL_HOST_USER,
        #     recipient_list=[user.email],
        # )

        send_email("Verify your email", f"Click the link to verify your email: {verification_link}", user.email)

        return data
