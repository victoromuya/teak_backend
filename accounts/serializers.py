# accounts/serializers.py

from rest_framework import serializers
from .models import User
from django.contrib.auth.password_validation import validate_password

from django.core.mail import send_mail
from django.conf import settings
from .utils.reset_tokens import generate_reset_token

from django.contrib.auth.password_validation import validate_password
from .utils.reset_tokens import verify_reset_token
from .utils.email_tokens import generate_email_verification_token

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'is_organizer']

    def create(self, validated_data):
        role = validated_data.pop("role", "user")

        user = User.objects.create_user(**validated_data)

        if role == "organizer":
            user.is_organizer = True
            user.save()

        return user


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = [
            "id",
            "username",
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

        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        print(reset_link)

        send_mail(
            subject="Reset your password",
            message=f"Click the link to reset your password: {reset_link}",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
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
        
        verification_link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        print(verification_link)
        # Send email
        send_mail(
            subject="Verify your email",
            message=f"Click the link to verify your email: {verification_link}",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user.email],
        )

        return data

class EmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate(self, data):
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            return data  # Do not reveal if user exists

        if user.is_email_verified:
            return data

        token = generate_email_verification_token(user)
        verification_link = f"{settings.FRONTEND_URL}/verify-email?token={token}"

        send_mail(
            subject="Verify your email",
            message=f"Click the link to verify your email: {verification_link}",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user.email]
        )

        return data