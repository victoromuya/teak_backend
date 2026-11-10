from django.utils import timezone
from uuid import UUID
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication


class ScopedJWTAuthentication(JWTAuthentication):
    """An email code grants ticket access, not account or organizer privileges."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if token.get('scope') != 'guest':
            return result
        if token.get('guest_until', 0) <= int(timezone.now().timestamp()):
            raise PermissionDenied('Guest access expired. Verify your email again.')
        path = request.path.rstrip('/')
        method = request.method
        try:
            order_id = UUID(path.split('/')[-1])
        except ValueError:
            order_id = None
        allowed = (
            (path == '/api/orders' and method in ('GET', 'POST'))
            or (path == '/api/orders/my-tickets' and method == 'GET')
            or (path.startswith('/api/orders/verify/') and method == 'GET' and token.get('guest_purpose') == 'guest_checkout')
            or (path.startswith('/api/orders/') and order_id is not None and method == 'GET')
            or (path == '/api/auth/user/profile' and method == 'GET')
        )
        if token.get('guest_purpose') == 'ticket_access' and method != 'GET':
            allowed = False
        if not allowed:
            raise PermissionDenied('Sign up or sign in to use this feature.')
        return result
