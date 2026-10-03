from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import EmailOTP
from .utils.reset_tokens import generate_reset_token


class AuthenticationSecurityTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            email="security@example.com", password="OldStrongPassword123!",
            is_email_verified=True,
        )

    def test_registration_rejects_weak_password_before_sending_email(self):
        with patch("accounts.serializers.send_email") as send:
            response = self.client.post("/api/auth/register/", {
                "email": "new-security@example.com", "password": "1",
            }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(email="new-security@example.com").exists())
        send.assert_not_called()

    def test_email_check_returns_identical_public_response(self):
        responses = [self.client.post("/api/auth/check-email/", {"email": email}, format="json")
                     for email in (self.user.email, "unknown-security@example.com")]
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(responses[0].data, responses[1].data)
        self.assertNotIn("exists", responses[0].data)

    @patch("accounts.serializers.send_email")
    def test_duplicate_registration_is_generic_and_preserves_account(self, send):
        original_password = self.user.password
        responses = [self.client.post("/api/auth/register/", {
            "email": email, "password": "NewStrongPassword987!", "first_name": "Requested",
        }, format="json") for email in (self.user.email.upper(), "new-hidden@example.com")]
        self.assertEqual([r.status_code for r in responses], [201, 201])
        self.assertEqual(responses[0].data, responses[1].data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, original_password)
        self.assertEqual(self.user.first_name, "")
        self.assertTrue(self.user.is_email_verified)
        self.assertFalse(EmailOTP.objects.filter(email=self.user.email).exists())
        self.assertEqual(send.call_count, 2)

    @patch("accounts.serializers.send_email")
    def test_guest_existing_account_gets_private_signin_instructions(self, send):
        responses = [self.client.post("/api/auth/email-verification/", {
            "email": email, "purpose": "guest_checkout", "first_name": "Guest",
        }, format="json") for email in (self.user.email, "new-guest-security@example.com")]
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(responses[0].data, responses[1].data)
        self.assertFalse(EmailOTP.objects.filter(email=self.user.email).exists())
        self.assertEqual(EmailOTP.objects.filter(email="new-guest-security@example.com").count(), 1)
        self.assertEqual(send.call_args_list[0].kwargs["action_label"], "Sign in")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldStrongPassword123!"))

    def test_non_object_login_body_is_rejected_without_server_error(self):
        for payload in ([], "invalid", 123):
            response = self.client.post("/api/auth/login/", payload, format="json")
            self.assertEqual(response.status_code, 400)

    def test_unknown_and_wrong_password_login_have_identical_errors(self):
        for url in ("/api/auth/login/", "/api/admin/auth/login/"):
            responses = [self.client.post(url, {"email": email, "password": "wrong"}, format="json")
                         for email in (self.user.email, "missing@example.com")]
            self.assertEqual([r.status_code for r in responses], [400, 400])
            self.assertEqual(responses[0].data, responses[1].data)

    def test_login_account_limit_applies_across_ips_and_email_casing(self):
        for index in range(11):
            response = self.client.post("/api/auth/login/", {
                "email": self.user.email.upper() if index % 2 else self.user.email,
                "password": "wrong",
            }, format="json", REMOTE_ADDR=f"192.0.2.{index + 1}")
            self.assertEqual(response.status_code, 400 if index < 10 else 429)
        self.assertIn("Retry-After", response)

    def test_registration_ip_limit_applies_across_email_addresses(self):
        for index in range(31):
            response = self.client.post("/api/auth/register/", {
                "email": f"limited-{index}@example.com", "password": "1",
            }, format="json")
            self.assertEqual(response.status_code, 400 if index < 30 else 429)

    def test_django_admin_login_is_rate_limited(self):
        for index in range(11):
            response = self.client.post("/admin/login/", {
                "username": self.user.email, "password": "wrong",
            })
            self.assertEqual(response.status_code, 200 if index < 10 else 429)

    def test_inactive_user_cannot_refresh(self):
        token = str(RefreshToken.for_user(self.user))
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.client.post("/api/auth/refresh/", {"refresh": token}, format="json").status_code, 401)

    def test_otp_locks_after_five_incorrect_guesses_even_from_other_ips(self):
        record = EmailOTP.objects.create(
            email=self.user.email, otp=make_password("123456"), purpose="registration",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        for index, code in enumerate(["000000"] * 5 + ["123456"]):
            response = self.client.post("/api/auth/verify-email/", {
                "email": self.user.email, "otp": code, "purpose": "registration",
            }, format="json", REMOTE_ADDR=f"192.0.2.{index + 1}")
            self.assertEqual(response.status_code, 400)
        record.refresh_from_db()
        self.assertEqual(record.failed_attempts, 5)
        self.assertFalse(record.is_used)

    def test_refresh_rotates_and_prevents_replay(self):
        old = str(RefreshToken.for_user(self.user))
        first = self.client.post("/api/auth/refresh/", {"refresh": old}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertNotEqual(first.data["refresh"], old)
        self.assertEqual(self.client.post("/api/auth/refresh/", {"refresh": old}, format="json").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/refresh/", {"refresh": first.data["refresh"]}, format="json").status_code, 200)

    def test_password_reset_revokes_access_and_refresh_tokens(self):
        refresh = RefreshToken.for_user(self.user)
        access = str(refresh.access_token)
        response = self.client.post("/api/auth/password-reset/confirm/", {
            "token": generate_reset_token(self.user), "new_password": "NewStrongPassword987!",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get("/api/auth/user/profile/").status_code, 401)
        self.client.credentials()
        self.assertEqual(self.client.post("/api/auth/refresh/", {"refresh": str(refresh)}, format="json").status_code, 401)
        login = self.client.post("/api/auth/login/", {
            "email": self.user.email, "password": "NewStrongPassword987!",
        }, format="json")
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.client.get("/api/auth/user/profile/").status_code, 200)

    def test_logout_prevents_refresh(self):
        token = str(RefreshToken.for_user(self.user))
        self.assertEqual(self.client.post("/api/auth/logout/", {"refresh": token}, format="json").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/refresh/", {"refresh": token}, format="json").status_code, 401)
