from rest_framework.permissions import BasePermission


class CanScanTicket(BasePermission):
    """
    Only the organizer of the event or an admin
    can scan tickets for that event.
    """

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and (
                request.user.is_staff
                or request.user.is_organizer
            )
        )

    def has_object_permission(self, request, view, obj):
        # obj is the Event instance

        if request.user.is_staff:
            return True

        return obj.organizer == request.user