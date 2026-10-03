from django.http import JsonResponse

from .throttles import AuthEmailThrottle, AuthThrottle


class AdminLoginThrottleMiddleware:
    """Apply the same shared login limits to Django's session admin login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path_info == "/admin/login/":
            for throttle in (AuthThrottle(), AuthEmailThrottle()):
                if not throttle.allow_request(request, self):
                    response = JsonResponse({"detail": "Too many login attempts. Try again later."}, status=429)
                    response["Retry-After"] = throttle.wait()
                    return response
        return self.get_response(request)
