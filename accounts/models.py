# accounts/models.py
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
import random



# class User(AbstractUser):
#     first_name = models.CharField(max_length=30)
#     last_name = models.CharField(max_length=30) 
    # is_organizer = models.BooleanField(default=False)
    # is_email_verified = models.BooleanField(default=False)
    

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_organizer = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = [] # Email and password are automatically required

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.email

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"




class EmailOTP(models.Model):

    PURPOSE_CHOICES = (
        ("registration", "Registration"),
        ("guest_checkout", "Guest Checkout"),
        ("login", "Login"),
        ("password_reset", "Password Reset"),
        ("email_change", "Email Change"),
    )

    email = models.EmailField(db_index=True)
    otp = models.CharField(max_length=300)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    purpose = models.CharField(
        max_length=30,
        choices=PURPOSE_CHOICES,
        default="registration",
    )

    is_used = models.BooleanField(default=False)

    expires_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "EmailOTPs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} - {self.purpose}"

    def is_expired(self):
        return timezone.now() > self.expires_at

    @staticmethod
    def generate_otp():
        return str(random.randint(100000, 999999))


