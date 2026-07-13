from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from .views import TicketTypeViewSet


class TicketTypePermissionTests(SimpleTestCase):
    def test_list_uses_permission_instances(self):
        view = TicketTypeViewSet()
        view.action = "list"

        permissions = view.get_permissions()

        self.assertEqual(len(permissions), 1)
        self.assertIsInstance(permissions[0], IsAuthenticatedOrReadOnly)

    def test_retrieve_uses_permission_instances(self):
        view = TicketTypeViewSet()
        view.action = "retrieve"

        permissions = view.get_permissions()

        self.assertEqual(len(permissions), 1)
        self.assertIsInstance(permissions[0], IsAuthenticatedOrReadOnly)
