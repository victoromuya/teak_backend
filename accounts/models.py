# accounts/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30) 
    is_organizer = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
