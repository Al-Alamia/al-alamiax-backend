from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import Profile

class ProfileTests(BaseUserTestCase):
    def test_get_profile(self):
        self.authenticate_as(self.agent)
        url = f"/api/users/profile?uuid={self.agent.profile.uuid}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Result is list or object? APIViewSet returns list for GET usually unless it's a detail view?
        # Standard APIViewSet.get handles pagination if pagination_class is set.
        # ProfileAPI has pagination_class = DefaultPagination
        self.assertIn("results", response.data)

    def test_update_own_profile(self):
        self.authenticate_as(self.agent)
        url = f"/api/users/profile?uuid={self.agent.profile.uuid}"
        data = {"about": "I am an agent"}
        response = self.client.put(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.about, "I am an agent")
