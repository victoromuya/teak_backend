from rest_framework import generics, status, permissions
from rest_framework.viewsets import ModelViewSet
# from .models import User
from .serializers import ContactSerializer, RegisterSerializer, UserSerializer, EmailVerificationRequestSerializer
from rest_framework.views import APIView

from .permissions import IsAdmin, IsOrganizer, IsNormalUser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count
from django.conf import settings
from glob_utils.send_email import send_email
from django.db import transaction
from django.http import HttpResponseRedirect
from urllib.parse import urlencode

from django.contrib.auth.hashers import make_password, check_password

from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from .utils.email_tokens import verify_email_token
from .serializers import (
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer, EmailCheckSerializer, VerifyEmailOTPSerializer
)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import CustomUser, EmailOTP


from drf_spectacular.utils import extend_schema
from rest_framework_simplejwt.views import TokenObtainPairView
from events.models import Event
from orders.models import Order, Ticket
from rest_framework_simplejwt.tokens import RefreshToken
from smtplib import SMTPException


User = get_user_model()


class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = LoginSerializer

@extend_schema(
    tags=["auth"],
    description="Register a new user"
)
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]  # Allow unauthenticated users to sign up

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except (SMTPException, OSError):
            return Response(
                {"detail": "Verification email could not be sent. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class OrganizerProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_organizer:
            return Response({"error": "Not an organizer"}, status=403)

        serializer = UserSerializer(request.user)

        events = Event.objects.filter(organizer=request.user)

        total_events = events.count()

        total_tickets_sold = Ticket.objects.filter(
            order__event__organizer=request.user,
            order__status="paid"
        ).count()

        total_revenue = Order.objects.filter(
            event__organizer=request.user,
            status="paid"
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        upcoming_events = events.filter(
            start_date__gte=timezone.now()
        ).count()

        return Response({
            "user": serializer.data,
            "stats": {
                "total_events": total_events,
                "tickets_sold": total_tickets_sold,
                "total_revenue": total_revenue,
                "upcoming_events": upcoming_events,
            }
        })
    
       

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
        serializer = UserSerializer(request.user)
        user_orders = Order.objects.filter(
            user=request.user,
            status="paid"  # if you track payment status
        ).aggregate(total=Count('id'))['total'] or 0

        return Response({
            "user": serializer.data,
            "stats": {
                "total_orders": user_orders,
            }
        })
    

    def put(self, request):

        serializer = UserSerializer(request.user, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=400)


class ActivateOrganizerView(APIView):
    """Explicit one-way enrollment into organizer capabilities."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.is_organizer:
            user.is_organizer = True
            user.save(update_fields=["is_organizer"])

        return Response(UserSerializer(user).data)


class ContactView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/m", block=True))
    def post(self, request):
        serializer = ContactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        send_email(
            subject=f"Contact form: {data['subject']}",
            body=(
                f"From: {data['name']} <{data['email']}>\n\n"
                f"{data['message']}"
            ),
            to_email=settings.CONTACT_EMAIL,
            heading="New website enquiry",
            reply_to=[data["email"]],
        )
        return Response({"success": True, "message": "Message sent successfully."})


@extend_schema(
    tags=["auth"],
    description="Request Password Reset link",
    request=PasswordResetRequestSerializer,
    responses={200: None}
)
class PasswordResetRequestView(APIView):

    @method_decorator(ratelimit(key="ip", rate="5/m", block=True))
    def post(self, request):

        serializer = PasswordResetRequestSerializer(data=request.data)

        try:
            if serializer.is_valid():
                return Response({"message": "If the email exists, a reset link was sent"})
        except (SMTPException, OSError):
            return Response(
                {"detail": "Reset email could not be sent. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(serializer.errors, status=400)

@extend_schema(
    tags=["auth"],
    description="Confirm Password Reset",
    request=PasswordResetConfirmSerializer,
    responses={200: None}
)
class PasswordResetConfirmView(APIView):

    def get(self, request):
        """Keep previously emailed API links working after the frontend move."""
        token = request.query_params.get("token", "")
        query = urlencode({"token": token}) if token else ""
        reset_url = (
            f"{settings.PASSWORD_RESET_FRONTEND_URL.rstrip('/')}/reset-password"
        )
        return HttpResponseRedirect(f"{reset_url}?{query}" if query else reset_url)

    @method_decorator(ratelimit(key="ip", rate="10/m", block=True))
    def post(self, request):

        serializer = PasswordResetConfirmSerializer(data=request.data)

        if serializer.is_valid():
            return Response({"message": "Password reset successful"})

        return Response(serializer.errors, status=400)

@extend_schema(
    tags=["auth"],
    description="Request email verification link",
    request=EmailVerificationRequestSerializer,
    responses={200: None}
)
class EmailVerificationRequestView(APIView):

    permission_classes = []

    @method_decorator(ratelimit(key="ip", rate="5/m", block=True))
    def post(self, request):
        serializer = EmailVerificationRequestSerializer(
            data=request.data
        )

        try:
            serializer.is_valid(raise_exception=True)
        except (SMTPException, OSError):
            return Response(
                {"detail": "Verification email could not be sent. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "If the email can be verified, a verification code has been sent."
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["auth"],
    description="Verify OTP",
    request=VerifyEmailOTPSerializer,
    responses={200: None}
)
class VerifyEmailView(APIView):

    permission_classes = []

    @method_decorator(ratelimit(key="ip", rate="10/m", block=True))
    @transaction.atomic
    def post(self, request):

        serializer = VerifyEmailOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]
        purpose = serializer.validated_data["purpose"]

        otp_record = EmailOTP.objects.select_for_update().filter(
            email=email,
            purpose=purpose,
            is_used=False,
        ).first()

        if otp_record is None:
            return Response(
                {"error": "Invalid OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not check_password(otp, otp_record.otp):
            return Response(
                {"error": "Invalid OTP."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if otp_record.is_expired():
            return Response(
                {"error": "OTP has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ===========================================
        # NORMAL REGISTRATION
        # ===========================================
        if purpose == "registration":

            try:
                user = User.objects.get(email=email)

            except User.DoesNotExist:
                return Response(
                    {"error": "User not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])

            otp_record.is_used = True
            otp_record.save(update_fields=["is_used"])

            return Response(
                {
                    "message": "Email verified successfully."
                },
                status=status.HTTP_200_OK,
            )

        # ===========================================
        # GUEST CHECKOUT
        # ===========================================
        elif purpose == "guest_checkout":

            user = User.objects.create_user(
                email=otp_record.email,
                first_name=otp_record.first_name,
                last_name=otp_record.last_name,
            )

            user.is_email_verified = True
            user.set_unusable_password()
            user.save()

            refresh = RefreshToken.for_user(user)

            otp_record.is_used = True
            otp_record.save(update_fields=["is_used"])

            return Response(
                {
                    "message": "Email verified successfully.",

                    "access": str(refresh.access_token),
                    "refresh": str(refresh),

                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                    }
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "error": "Invalid verification purpose."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    


@extend_schema(
    tags=["auth"],
    description="Check Email",
    request=EmailCheckSerializer,
    responses={200: None}
)
@api_view(["POST"])
@permission_classes([AllowAny])
def check_email(request):

    serializer = EmailCheckSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    email = serializer.validated_data["email"]

    exists = CustomUser.objects.filter(
        email__iexact=email
    ).exists()

    return Response({
        "exists": exists
    })
