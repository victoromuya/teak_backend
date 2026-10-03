from accounts.throttles import AuthThrottle
from .models import Event


class EnquiryRecipientThrottle(AuthThrottle):
    dimension = "recipient"

    def get_recipient(self, view):
        try:
            event_id = int(view.kwargs.get("pk", ""))
        except (TypeError, ValueError):
            return "unknown"
        organizer_id = Event.objects.filter(pk=event_id).values_list("organizer_id", flat=True).first()
        return str(organizer_id) if organizer_id else "unknown"
