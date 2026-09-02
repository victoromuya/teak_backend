# accounts/serializers.py

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from .utils.reset_tokens import generate_reset_token
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.password_validation import validate_password
from .utils.reset_tokens import verify_reset_token
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from glob_utils.send_email import send_email
from .models import CustomUser, EmailOTP
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


@transaction.atomic
def issue_email_otp(*, email, purpose, first_name="", last_name=""):
    """Replace any active code and send exactly the code stored for verification."""
    EmailOTP.objects.filter(email=email, purpose=purpose, is_used=False).delete()
    plain_otp = EmailOTP.generate_otp()
    EmailOTP.objects.create(
        email=email,
        otp=make_password(plain_otp),
        first_name=first_name,
        last_name=last_name,
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    send_email(
        subject="Verify your email",
        body=f"Your verification code is {plain_otp}. It expires in 10 minutes.",
        to_email=email,
    )



class EmailCheckSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ContactSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    subject = serializers.CharField(max_length=200)
    message = serializers.CharField(min_length=20, max_length=5000)

    def validate_subject(self, value):
        if "\n" in value or "\r" in value:
            raise serializers.ValidationError("Subject must not contain line breaks.")
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'password', 'first_name', 'last_name', 'is_organizer']
        read_only_fields = ['id', 'is_organizer']

    
    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        with transaction.atomic():
            user = User.objects.create_user(**validated_data)
            issue_email_otp(
                email=user.email,
                purpose="registration",
                first_name=user.first_name,
                last_name=user.last_name,
            )
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

        if not user.is_email_verified:
            raise serializers.ValidationError({
                "detail": "Verify your email address before logging in."
            })


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
        read_only_fields = ["id", "email", "is_organizer"]



class PasswordResetRequestSerializer(serializers.Serializer):

    email = serializers.EmailField()

    def validate(self, data):
        email = data["email"].strip().lower()
        data["email"] = email

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return data  # do not reveal if email exists

        token = generate_reset_token(user)
        reset_link = (
            f"{settings.PASSWORD_RESET_FRONTEND_URL.rstrip('/')}/reset-password"
            f"?token={token}"
        )
        
        send_email(
            "Reset your password",
            "We received a request to reset your TickFirst password. "
            "Use the secure button below to choose a new password. If you did "
            "not request this, you can safely ignore this email.\n\n"
            f"{reset_link}",
            user.email,
            heading="Reset your password",
            action_label="Reset password",
            action_url=reset_link,
        )


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
        user.is_email_verified = True
        user.save(update_fields=["password", "is_email_verified"])

        return data


class EmailVerificationRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    purpose = serializers.ChoiceField(choices=("registration", "guest_checkout"))
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        email = data["email"].lower()
        purpose = data["purpose"]
        first_name = data["first_name"].strip()
        last_name = data["last_name"].strip()
        data["email"] = email

        # Don't reveal whether the email exists
        user = CustomUser.objects.filter(email=email).first()

        if user and user.is_email_verified:
            return data

        issue_email_otp(
            email=email,
            first_name=first_name,
            last_name=last_name,
            purpose=purpose,
        )

        return data
    


class VerifyEmailOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)
    purpose = serializers.ChoiceField(
        choices=[
            ("registration", "Registration"),
            ("guest_checkout", "Guest Checkout"),
        ]
    )

    def validate_email(self, value):
        return value.strip().lower()
