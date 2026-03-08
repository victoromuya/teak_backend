# accounts/utils/email_tokens.py

import jwt
from datetime import datetime, timedelta
from django.conf import settings

EMAIL_SECRET = settings.SECRET_KEY

def generate_email_verification_token(user):
    payload = {
        "user_id": user.id,
        "exp": datetime.utcnow() + timedelta(hours=24),  # expires in 24h
        "type": "email_verification"
    }
    token = jwt.encode(payload, EMAIL_SECRET, algorithm="HS256")
    return token

def verify_email_token(token):
    import jwt
    try:
        payload = jwt.decode(token, EMAIL_SECRET, algorithms=["HS256"])
        if payload.get("type") != "email_verification":
            return None
        return payload["user_id"]
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None