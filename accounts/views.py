from rest_framework import generics, status
from rest_framework.viewsets import ModelViewSet
from .models import User
from .serializers import RegisterSerializer, UserSerializer
from rest_framework.views import APIView

from .permissions import IsAdmin, IsOrganizer, IsNormalUser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count

from django.utils import timezone
from datetime import timedelta

from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from .utils.email_tokens import verify_email_token
from .serializers import (
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer
)



class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer


class OrganizerProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_organizer:
            return Response({"error": "Not an organizer"}, status=403)

        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        if not request.user.is_organizer:
            return Response({"error": "Not an organizer"}, status=403)

        serializer = UserSerializer(request.user, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=400)


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.is_organizer:
            return Response({"error": "Organizer cannot use this endpoint"}, status=403)

        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class PasswordResetRequestView(APIView):

    @method_decorator(ratelimit(key="ip", rate="5/m", block=True))
    def post(self, request):

        serializer = PasswordResetRequestSerializer(data=request.data)

        if serializer.is_valid():
            return Response({"message": "If the email exists, a reset link was sent"})

        return Response(serializer.errors, status=400)


class PasswordResetConfirmView(APIView):

    @method_decorator(ratelimit(key="ip", rate="10/m", block=True))
    def post(self, request):

        serializer = PasswordResetConfirmSerializer(data=request.data)

        if serializer.is_valid():
            return Response({"message": "Password reset successful"})

        return Response(serializer.errors, status=400)


class EmailVerificationRequestView(APIView):

    def post(self, request):
        serializer = EmailVerificationRequestSerializer(data=request.data)
        if serializer.is_valid():
            return Response({"message": "If the email exists, a verification link was sent."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifyEmailView(APIView):

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response({"error": "Token is required"}, status=400)

        user_id = verify_email_token(token)
        if not user_id:
            return Response({"error": "Invalid or expired token"}, status=400)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        if user.is_email_verified:
            return Response({"message": "Email already verified"}, status=200)

        user.is_email_verified = True
        user.save()

        return Response({"message": "Email verified successfully"}, status=200)


