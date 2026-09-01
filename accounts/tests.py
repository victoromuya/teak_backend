from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from smtplib import SMTPException

from .models import EmailOTP


class RoleProtectionTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="role-user@example.com",
            password="password123",
        )
        self.client.force_authenticate(self.user)

    def test_profile_update_cannot_change_role_or_email(self):
        response = self.client.put(
            "/api/auth/user/profile/",
            {
                "first_name": "Updated",
                "email": "attacker@example.com",
                "is_organizer": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.email, "role-user@example.com")
        self.assertFalse(self.user.is_organizer)

    def test_dedicated_activation_is_authenticated_and_idempotent(self):
        first = self.client.post("/api/auth/organizer/activate/")
        second = self.client.post("/api/auth/organizer/activate/")

        self.user.refresh_from_db()
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(self.user.is_organizer)

    def test_activation_rejects_anonymous_request(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/auth/organizer/activate/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_registration_cannot_self_assign_organizer_role(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/auth/register/",
            {
                "email": "new-role-user@example.com",
                "password": "StrongPassword123!",
                "first_name": "New",
                "last_name": "User",
                "is_organizer": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_user = get_user_model().objects.get(email="new-role-user@example.com")
        self.assertFalse(created_user.is_organizer)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ContactEndpointTests(APITestCase):
    def test_public_contact_endpoint_sends_message(self):
        response = self.client.post(
            "/api/contact/send-mail/",
            {
                "name": "Site Visitor",
                "email": "visitor@example.com",
                "subject": "Ticket assistance",
                "message": "I need assistance locating my purchased event ticket.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, ["visitor@example.com"])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_URL="https://frontend.example",
    PASSWORD_RESET_FRONTEND_URL="https://frontend.example",
)
class AuthenticationEmailFlowTests(APITestCase):
    def register(self, email="new-user@example.com"):
        return self.client.post(
            "/api/auth/register/",
            {
                "email": email,
                "password": "StrongPassword123!",
                "first_name": "New",
                "last_name": "User",
            },
            format="json",
        )

    @patch("accounts.models.EmailOTP.generate_otp", return_value="123456")
    def test_registration_sends_otp_and_verification_consumes_it(self, _generate):
        response = self.register("MixedCase@Example.com")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["mixedcase@example.com"])
        self.assertIn("123456", mail.outbox[0].body)
        self.assertIn("10 minutes", mail.outbox[0].body)

        verification = self.client.post(
            "/api/auth/verify-email/",
            {
                "email": "MIXEDCASE@EXAMPLE.COM",
                "otp": "123456",
                "purpose": "registration",
            },
            format="json",
        )
        self.assertEqual(verification.status_code, status.HTTP_200_OK)
        user = get_user_model().objects.get(email="mixedcase@example.com")
        self.assertTrue(user.is_email_verified)

        reuse = self.client.post(
            "/api/auth/verify-email/",
            {
                "email": user.email,
                "otp": "123456",
                "purpose": "registration",
            },
            format="json",
        )
        self.assertEqual(reuse.status_code, status.HTTP_400_BAD_REQUEST)

    @patch(
        "accounts.models.EmailOTP.generate_otp",
        side_effect=["111111", "222222"],
    )
    def test_resend_invalidates_previous_registration_otp(self, _generate):
        self.register()
        resend = self.client.post(
            "/api/auth/email-verification/",
            {
                "email": "new-user@example.com",
                "purpose": "registration",
                "first_name": "New",
                "last_name": "User",
            },
            format="json",
        )
        self.assertEqual(resend.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("222222", mail.outbox[1].body)

        old_code = self.client.post(
            "/api/auth/verify-email/",
            {
                "email": "new-user@example.com",
                "otp": "111111",
                "purpose": "registration",
            },
            format="json",
        )
        self.assertEqual(old_code.status_code, status.HTTP_400_BAD_REQUEST)

    def test_expired_otp_is_rejected(self):
        user = get_user_model().objects.create_user(email="expired@example.com")
        EmailOTP.objects.create(
            email=user.email,
            otp=make_password("123456"),
            purpose="registration",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        response = self.client.post(
            "/api/auth/verify-email/",
            {
                "email": user.email,
                "otp": "123456",
                "purpose": "registration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "OTP has expired.")

    @patch("accounts.models.EmailOTP.generate_otp", return_value="654321")
    def test_guest_checkout_otp_sends_email_and_creates_verified_account(self, _generate):
        request = self.client.post(
            "/api/auth/email-verification/",
            {
                "email": "Guest@Example.com",
                "purpose": "guest_checkout",
                "first_name": "Guest",
                "last_name": "Buyer",
            },
            format="json",
        )
        self.assertEqual(request.status_code, status.HTTP_200_OK)
        self.assertEqual(mail.outbox[0].to, ["guest@example.com"])
        self.assertIn("654321", mail.outbox[0].body)

        verification = self.client.post(
            "/api/auth/verify-email/",
            {
                "email": "guest@example.com",
                "otp": "654321",
                "purpose": "guest_checkout",
            },
            format="json",
        )
        self.assertEqual(verification.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", verification.data)
        user = get_user_model().objects.get(email="guest@example.com")
        self.assertTrue(user.is_email_verified)
        self.assertFalse(user.has_usable_password())

    def test_invalid_otp_purpose_is_rejected_without_sending(self):
        response = self.client.post(
            "/api/auth/email-verification/",
            {
                "email": "user@example.com",
                "purpose": "admin_login",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_email_link_changes_password_once(self):
        user = get_user_model().objects.create_user(
            email="reset@example.com",
            password="OldPassword123!",
        )
        request = self.client.post(
            "/api/auth/password-reset/request/",
            {"email": user.email},
            format="json",
        )
        self.assertEqual(request.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])

        reset_url = mail.outbox[0].body.split()[-1]
        parsed = urlparse(reset_url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "frontend.example")
        self.assertEqual(parsed.path, "/reset-password")
        token = parse_qs(parsed.query)["token"][0]

        confirmation = self.client.post(
            "/api/auth/password-reset/confirm/",
            {"token": token, "new_password": "NewPassword456!"},
            format="json",
        )
        self.assertEqual(confirmation.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewPassword456!"))
        self.assertTrue(user.is_email_verified)

        reuse = self.client.post(
            "/api/auth/password-reset/confirm/",
            {"token": token, "new_password": "AnotherPassword789!"},
            format="json",
        )
        self.assertEqual(reuse.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_does_not_disclose_unknown_email(self):
        response = self.client.post(
            "/api/auth/password-reset/request/",
            {"email": "missing@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_legacy_api_reset_link_redirects_to_frontend(self):
        response = self.client.get(
            "/api/auth/password-reset/confirm/",
            {"token": "legacy-token"},
        )

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(
            response.url,
            "https://frontend.example/reset-password?token=legacy-token",
        )

    def test_unverified_account_cannot_log_in(self):
        get_user_model().objects.create_user(
            email="unverified@example.com",
            password="StrongPassword123!",
        )
        response = self.client.post(
            "/api/auth/login/",
            {"email": "unverified@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Verify your email", str(response.data))

    def test_verified_account_can_log_in(self):
        get_user_model().objects.create_user(
            email="verified@example.com",
            password="StrongPassword123!",
            is_email_verified=True,
        )
        response = self.client.post(
            "/api/auth/login/",
            {"email": "verified@example.com", "password": "StrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    @patch("accounts.serializers.send_email", side_effect=SMTPException("offline"))
    def test_registration_email_failure_is_reported_and_rolls_back_user(self, _send):
        response = self.register("delivery-failure@example.com")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(
            get_user_model().objects.filter(email="delivery-failure@example.com").exists()
        )
