# accounts/utils/reset_tokens.py

import jwt
import hashlib
import hmac
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.auth import get_user_model


RESET_SECRET = settings.SECRET_KEY


def generate_reset_token(user):

    payload = {
        "user_id": user.id,
        "exp": datetime.utcnow() + timedelta(minutes=15),
        "type": "password_reset",
        "password_fingerprint": hashlib.sha256(user.password.encode()).hexdigest(),
    }

    token = jwt.encode(payload, RESET_SECRET, algorithm="HS256")

    return token


def verify_reset_token(token):

    try:
        payload = jwt.decode(token, RESET_SECRET, algorithms=["HS256"])

        if payload["type"] != "password_reset":
            return None

        user = get_user_model().objects.filter(id=payload["user_id"]).first()
        if user is None:
            return None
        expected = hashlib.sha256(user.password.encode()).hexdigest()
        if not hmac.compare_digest(payload.get("password_fingerprint", ""), expected):
            return None
        return user.id

    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
