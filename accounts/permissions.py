# accounts/permissions.py

from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_staff


class IsOrganizer(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_organizer


class IsNormalUser(BasePermission):
    def has_permission(self, request, view):
        return request.user and not request.user.is_organizer