# accounts/utils/reset_tokens.py

import jwt
from datetime import datetime, timedelta
from django.conf import settings


RESET_SECRET = settings.SECRET_KEY


def generate_reset_token(user):

    payload = {
        "user_id": user.id,
        "exp": datetime.utcnow() + timedelta(minutes=15),
        "type": "password_reset"
    }

    token = jwt.encode(payload, RESET_SECRET, algorithm="HS256")

    return token


def verify_reset_token(token):

    try:
        payload = jwt.decode(token, RESET_SECRET, algorithms=["HS256"])

        if payload["type"] != "password_reset":
            return None

        return payload["user_id"]

    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None