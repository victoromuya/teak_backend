Required before deployment
Add a Passenger startup file

Namecheap does not use the repository’s Procfile. Create passenger_wsgi.py in the application root:
from tick_backend.wsgi import application

Then configure:
Startup file: passenger_wsgi.py
Entry point: application
Python: 3.11, 3.12, or 3.13
This matches Namecheap’s official Django deployment procedure.
Configure the production hostname
The Namecheap API hostname is missing from [settings.py (line 24)](C:/Users/HOME/Documents/TikBackend/tick_backend/settings.py:24). For an API at api.example.com, configure:
ALLOWED_HOSTS = ["api.example.com"]

CORS_ALLOWED_ORIGINS = [
    "https://example.com",
    "https://www.example.com",
]

CSRF_TRUSTED_ORIGINS = [
    "https://api.example.com",
]

These should ideally come from environment variables rather than being hard-coded.

Use a production database
The application defaults to SQLite in [settings.py (line 87)](C:/Users/HOME/Documents/TikBackend/tick_backend/settings.py:87). SQLite may technically start, but it is a poor production choice for this ticketing application because concurrent payments and ticket inventory updates can produce database-lock contention.

Use PostgreSQL through DATABASE_URL. Namecheap’s current plan comparison shows PostgreSQL availability varies by plan, so confirm the selected shared plan supports it. 

Namecheap shared-hosting comparison
Add production security settings
manage.py check --deploy completed but reported missing production HTTPS protections. 

Add after SSL is enabled:
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
Enable HSTS only after confirming HTTPS works on every affected subdomain.
Configure environment variables in cPanel

The application requires:
SECRET_KEY
DEBUG=False
DATABASE_URL
FRONTEND_URL=https://example.com
PAYSTACK_SECRET_KEY
EMAIL_HOST_PASSWORD
TICKET_PLATFORM_FEE_PERCENTAGE=5.00
CLOUDSTORE_API_KEY
CLOUDSTORE_API_SECRET

Namecheap’s Python App interface supports environment variables directly.
Fix or test synchronous external operations
Paystack, Cloudinary, and email calls are synchronous. That is compatible with WSGI, but they occupy a limited Passenger worker while running.
One Paystack initialization request has no timeout in [orders/views.py (line 143)](C:/Users/HOME/Documents/TikBackend/orders/views.py:143). Add one:
response = requests.post(
    ...,
    timeout=10,
)

Ticket generation also creates QR images, uploads each to Cloudinary, and sends email during the request in [orders/views.py (line 468)](C:/Users/HOME/Documents/TikBackend/orders/views.py:468). 

Large ticket orders could exceed shared-hosting request limits. It should be acceptable for low traffic and small orders, but a VPS/background worker would eventually be preferable.

Gmail SMTP on port 465 must be tested from the hosting account. Namecheap supports authenticated SMTP on port 465 for its own hosted mail, but third-party Gmail connectivity and Gmail authentication policy remain separate concerns. Namecheap SMTP settings

React coexistence
No React project exists in this repository, so I could not validate its 
build or API URL configuration. 

The recommended layout is:
https://example.com       React production build in public_html
https://api.example.com   Django Passenger application
Build React locally and upload the generated dist/build directory to public_html. Configure React’s production API base URL as https://api.example.com, and add an SPA rewrite so routes such as /events/123 return index.html.
