# Security deployment

Apply `python manage.py migrate --noinput` before routing traffic to the updated
backend. The authentication limits and OTP attempt counter require accounts
migration 0007. Deploy the frontend update with the backend: refresh responses
now contain a replacement refresh token that clients must persist.

Existing tokens without the password fingerprint will be rejected after this
deployment. Users must sign in again. Access tokens expire after 10 minutes;
refresh tokens rotate and their previous values are blacklisted. Password
changes invalidate both token types. Logout blacklists the refresh token;
an already-issued access token remains valid until its 10-minute expiry unless
the password changes or the account is disabled. Schedule Django's
`flushexpiredtokens` command daily to prune expired JWT records.

## HTTPS and proxy configuration

- Set `DEBUG=False` in production. HTTPS redirection, Secure session/CSRF cookies,
  and an initial one-hour HSTS policy are enabled automatically.
- If TLS terminates at a reverse proxy, configure it to discard client-supplied
  `X-Forwarded-Proto` and set the header itself. Only then set
  `TRUST_PROXY_SSL_HEADER=True`. Otherwise HTTPS redirect loops are possible.
- Restrict backend ingress to the trusted proxy. Review `ALLOWED_HOSTS`, frontend
  URLs, and CSRF origins for the deployment. Localhost CORS/CSRF origins are
  excluded when debug is off.
- Increase HSTS duration only after HTTPS works across the intended hosts.
  Subdomain inclusion and preload are deliberately not enabled.
- Run `python manage.py check --deploy` with the real production configuration.
  Verify HTTPS redirects, cookies, headers, login, checkout, and logout in staging.
- Frontend Vercel configuration adds anti-framing, MIME-sniffing, referrer, HSTS,
  and limited CSP protections. Mirror these headers if hosting elsewhere.
  The CSP is not a complete script-source restriction.

## Authentication limits

Limits use atomic database counters, shared across workers without Redis. Login
limits are 30 requests per IP and 10 per normalized email per minute; Django admin
and API login share those counters. Registration, password-reset requests, and
OTP requests share 30/IP and 5/email per hour. OTP verification is also limited
by IP/email, and each issued code permits at most five incorrect guesses.
Refresh requests are limited to 60/IP per minute. Windows are fixed, not sliding.
Expired counter records are removed during subsequent authentication requests.

Checkout permits at most 20 tickets per order, summed across all ticket types,
and at most 20 item rows. Checkout attempts are limited to 10/account and 30/IP
per minute. The frontend reads the ticket cap from `/api/platform-config/`.
Organizer enquiries are limited to 5/sender, 30/IP, and 20/recipient per hour;
the recipient quota is shared across that organizer's events. Limits count
requests, including invalid requests, and return HTTP 429 with Retry-After.

Public ticket-type lists/details follow event visibility. Owners and admins
retain access to their own management/history data. Email checks and duplicate
registration return generic responses. Existing guest account holders receive
private sign-in instructions instead of a new account or new credentials.

IP limits use `REMOTE_ADDR`, not untrusted forwarding headers. Configure the
trusted ingress/WSGI layer to provide the real client address, or add per-client
edge limits; otherwise users behind one proxy may share an IP quota. Add edge
request/body limits to protect the database from volumetric abuse.

## Remaining authentication work

Tokens still use browser localStorage. Moving refresh credentials to HttpOnly
cookies requires a coordinated cookie/CSRF flow. Administrator MFA is not yet
implemented. Generic responses remove explicit account-existence disclosures;
this is not a guarantee against all timing-based side channels.

Concurrency regression tests simulate stale reads deterministically. Run the
full suite against PostgreSQL in CI as well; SQLite does not exercise PostgreSQL
row locking. No live infrastructure changes are performed by this patch.
