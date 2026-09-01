from django.test import Client, TestCase, override_settings


@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost"],
    CSRF_COOKIE_NAME="tickfirst_csrftoken",
)
class AdminCsrfTests(TestCase):
    def test_fresh_admin_form_token_is_accepted(self):
        client = Client(enforce_csrf_checks=True)
        login_page = client.get("/admin/login/?next=/admin/")
        csrf_token = login_page.cookies["tickfirst_csrftoken"].value

        response = client.post(
            "/admin/login/?next=/admin/",
            {
                "username": "unknown@example.com",
                "password": "wrong-password",
                "csrfmiddlewaretoken": csrf_token,
            },
        )

        # Invalid credentials redisplay the form; a CSRF failure returns 403.
        self.assertEqual(login_page.status_code, 200)
        self.assertEqual(response.status_code, 200)

    def test_legacy_default_csrf_cookie_cannot_collide(self):
        client = Client(enforce_csrf_checks=True)
        client.cookies["csrftoken"] = "stale-token-from-another-local-app"

        response = client.get("/admin/login/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("tickfirst_csrftoken", response.cookies)
