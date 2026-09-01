import os

import dj_database_url

from .settings import *  # noqa: F403


test_database_url = os.getenv(
    "TEST_DATABASE_URL",
    f"sqlite:///{BASE_DIR / '.test.sqlite3'}",  # noqa: F405
)
DATABASES = {"default": dj_database_url.parse(test_database_url)}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

MEDIA_ROOT = BASE_DIR / ".test-media"  # noqa: F405
