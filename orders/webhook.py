import hashlib
import hmac
import json

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from .services import (
    InsufficientInventoryError,
    InvalidPaymentError,
    OrderNotFoundError,
    finalize_paystack_payment,
)


@csrf_exempt
def paystack_webhook(request):
    body = request.body
    signature = request.headers.get("x-paystack-signature")
    computed_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        body,
        hashlib.sha512,
    ).hexdigest()

    if not signature or not hmac.compare_digest(computed_signature, signature):
        return HttpResponse(status=400)

    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return HttpResponse(status=400)

    if payload.get("event") != "charge.success":
        return HttpResponse(status=200)

    payment_data = payload.get("data", {})
    try:
        finalize_paystack_payment(payment_data.get("reference"), payment_data)
    except OrderNotFoundError:
        return HttpResponse(status=404)
    except (InvalidPaymentError, InsufficientInventoryError):
        return HttpResponse(status=400)

    return HttpResponse(status=200)
