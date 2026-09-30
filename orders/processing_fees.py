from decimal import Decimal, ROUND_CEILING

from django.conf import settings


def payment_breakdown(subtotal):
    """Gross up one NGN payment, including fees on the surcharge itself."""
    subtotal = Decimal(subtotal)
    if subtotal == 0:
        return Decimal("0.00"), Decimal("0.00")
    cent = Decimal("0.01")
    rate = Decimal(str(settings.PAYSTACK_FEE_PERCENTAGE)) / Decimal("100")
    flat = Decimal(str(settings.PAYSTACK_FEE_FLAT_AMOUNT))
    threshold = Decimal(str(settings.PAYSTACK_FEE_FLAT_THRESHOLD))
    cap = Decimal(str(settings.PAYSTACK_FEE_CAP))

    # The waiver threshold applies to the amount charged, including the fee.
    payable = (subtotal / (1 - rate)).quantize(cent, rounding=ROUND_CEILING)
    if payable >= threshold:
        payable = ((subtotal + flat) / (1 - rate)).quantize(cent, rounding=ROUND_CEILING)
    payable = min(payable, subtotal + cap)
    return payable - subtotal, payable
