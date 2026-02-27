# accounts/serializers.py

from rest_framework import serializers
from .models import User
from django.contrib.auth.password_validation import validate_password

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'is_organizer']

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user
