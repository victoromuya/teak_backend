import hmac
import hashlib
import json
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from .models import Order
from events.models import TicketType


@csrf_exempt
def paystack_webhook(request):
    payload = request.body

    # TEMPORARY: Skip signature validation for local testing
    if settings.DEBUG:
        event = json.loads(payload)
    else:
        signature = request.headers.get("x-paystack-signature")

        computed = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(),
            payload,
            hashlib.sha512
        ).hexdigest()

        if computed != signature:
            return HttpResponse(status=400)

        event = json.loads(payload)


# @csrf_exempt
# def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature")
    body = request.body

    computed_hash = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        body,
        hashlib.sha512
    ).hexdigest()

    if computed_hash != signature:
        return HttpResponse(status=400)

    payload = json.loads(body)

    if payload["event"] == "charge.success":
        reference = payload["data"]["reference"]

        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(reference=reference)
            except Order.DoesNotExist:
                return HttpResponse(status=404)

            if order.status == "paid":
                return HttpResponse(status=200)

            order.status = "paid"
            order.save()

            # Deduct stock safely
            for item in order.items.select_related("ticket_type"):
                ticket = item.ticket_type
                ticket.quantity -= item.quantity
                ticket.save()

    return HttpResponse(status=200)