# Checkout processing fees

New paid orders save three amounts:

- `total_amount`: ticket subtotal, used for organizer/platform revenue splitting.
- `processing_fee`: the buyer-funded processing charge, calculated once per order.
- `payment_amount`: the sum, displayed at checkout, sent to Paystack in kobo,
  and checked by both callback and webhook payment verification.

Free orders have no processing charge. Existing orders keep their original
payment amounts, including pending orders already initialized with Paystack.
Later fee configuration changes do not reprice an existing order.

## Environment configuration

```dotenv
TICKET_PLATFORM_FEE_PERCENTAGE=6.00
PAYSTACK_FEE_PERCENTAGE=1.5
PAYSTACK_FEE_FLAT_AMOUNT=100.00
PAYSTACK_FEE_FLAT_THRESHOLD=2500.00
PAYSTACK_FEE_CAP=2000.00
```

The `PAYSTACK_FEE_*` defaults represent standard Nigerian local online payments.
The split percentage is required; it has no hardcoded fallback. Set values in
the deployed backend environment and restart it after changes.

The backend grosses up the payment to cover the fee on the added charge too,
rounds upward to the nearest kobo, applies the fixed-fee waiver to the full
charge, and caps the fee. A NGN 10,000 ticket becomes NGN 10,253.81 under these
defaults; the revenue split still applies to NGN 10,000 only.

## Deployment

1. Disable **Settings > Preferences > Transaction fees > Pass fees to customers**
   in Paystack. This application adds the fee itself; automatic passing would
   charge twice. The application does not change that account setting.
2. Confirm the pricing profile matches the Paystack account. International cards
   and negotiated pricing may have different fees. This implementation uses one
   configured pricing profile, not automatic card-origin detection; a local
   quote does not guarantee recovery of international-card fees.
3. Run `python manage.py migrate` before starting the updated backend. Migration
   `0005` backfills the organizer/platform revenue shares; `0006` preserves the
   original payment totals of existing orders with zero buyer processing fee.
4. Deploy the backend and frontend together. No live database migration or
   Paystack-account setting change is performed by these code changes.

Paystack pricing and markup guidance:
https://support.paystack.com/en/articles/2130306
