from rest_framework.permissions import BasePermission


class CanDeleteEvent(BasePermission):
    """
    Admin can delete any event.
    Organizer can delete only their own event.
    """

    def has_object_permission(self, request, view, obj):

        # Admin
        if request.user.is_staff:
            return True

        # Organizer (only their event)
        if request.user.is_authenticated and request.user.is_organizer:
            return obj.organizer == request.user

        return False

class IsOrganizer(BasePermission):
    """
    Allows access only to users marked as organizers.
    """

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.is_organizer
        )

class IsOrganizerOrAdmin(BasePermission):
    """
    Allow only organizers or admin to create events
    """

    def has_permission(self, request, view):

        # Must be logged in
        if not request.user.is_authenticated:
            return False

        # Admin
        if request.user.is_staff:
            return True

        # Organizer
        if hasattr(request.user, "is_organizer") and request.user.is_organizer:
            return True

        return False