from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()


class AdminAuthEndpointsTests(APITestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            email="admin@example.com",
            password="AdminPass123!",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )
        self.normal_user = User.objects.create_user(
            email="user@example.com",
            password="UserPass123!",
            first_name="Normal",
            last_name="User",
        )

    def test_admin_login_returns_tokens_for_staff_user(self):
        response = self.client.post(
            "/api/admin/auth/login/",
            {"email": "admin@example.com", "password": "AdminPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], self.admin_user.email)
        self.assertTrue(response.data["user"]["is_staff"])

    def test_admin_login_rejects_non_admin_user(self):
        response = self.client.post(
            "/api/admin/auth/login/",
            {"email": "user@example.com", "password": "UserPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"][0],
            "You do not have admin access.",
        )

    def test_admin_me_returns_current_admin(self):
        token = RefreshToken.for_user(self.admin_user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.get("/api/admin/auth/me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], self.admin_user.email)
        self.assertTrue(response.data["user"]["is_staff"])

    def test_admin_me_rejects_non_admin_user(self):
        token = RefreshToken.for_user(self.normal_user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.get("/api/admin/auth/me/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
