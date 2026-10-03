import hashlib
import math
from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from rest_framework.throttling import BaseThrottle

from .models import AuthRateLimit


class AuthThrottle(BaseThrottle):
    """Atomic fixed-window limits shared by all workers through the database."""

    dimension = "ip"

    def allow_request(self, request, view):
        group = getattr(view, "auth_limit_group", "login")
        limits = {
            "login": (60, 30, 10),
            "email": (3600, 30, 5),
            "otp": (60, 30, 10),
            "refresh": (60, 60, 60),
            "checkout": (60, 30, 10),
            "enquiry": (3600, 30, 5),
        }
        window, ip_limit, email_limit = limits[group]
        identity = request.META.get("REMOTE_ADDR", "unknown")
        limit = ip_limit
        if self.dimension == "user":
            identity = str(request.user.pk)
            limit = email_limit
        if self.dimension == "recipient":
            identity = self.get_recipient(view)
            limit = 20
        if self.dimension == "email":
            data = getattr(request, "data", None)
            if data is None:
                data = request.POST
            if not hasattr(data, "get"):
                return True  # Serializer validation will reject non-object JSON.
            identity = data.get("email", data.get("username", ""))
            if not isinstance(identity, str) or not identity.strip():
                return True
            identity = identity.strip().lower()
            limit = email_limit
        now = timezone.now()
        bucket = int(now.timestamp()) // window
        key = hashlib.sha256(f"{group}:{self.dimension}:{bucket}:{identity}".encode()).hexdigest()
        # Bounded retention; no addresses or tokens are stored in clear text.
        AuthRateLimit.objects.filter(expires_at__lt=now).delete()
        AuthRateLimit.objects.get_or_create(
            key=key, defaults={"expires_at": now + timedelta(seconds=window * 2)}
        )
        allowed = AuthRateLimit.objects.filter(key=key, count__lt=limit).update(count=F("count") + 1)
        self.retry_after = math.ceil(window - now.timestamp() % window)
        return bool(allowed)

    def wait(self):
        return self.retry_after


class AuthEmailThrottle(AuthThrottle):
    dimension = "email"


class AuthUserThrottle(AuthThrottle):
    dimension = "user"
