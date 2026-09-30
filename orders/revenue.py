from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings


CENT = Decimal("0.01")


def split_revenue(total_amount, items):
    """Round the organizer's share per ticket, keeping every kobo accounted for."""
    gross = Decimal(total_amount)
    organizer_rate = (Decimal("100") - Decimal(str(settings.TICKET_PLATFORM_FEE_PERCENTAGE))) / Decimal("100")
    items = list(items)
    if items and sum(item.price * item.quantity for item in items) == gross:
        organizer = sum(
            (item.price * organizer_rate).quantize(CENT, rounding=ROUND_HALF_UP)
            * item.quantity
            for item in items
        )
    else:
        # Historical/imported orders may not have item records.
        organizer = (gross * organizer_rate).quantize(CENT, rounding=ROUND_HALF_UP)
    return organizer, gross - organizer
