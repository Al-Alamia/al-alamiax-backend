from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import User

class UserTests(BaseUserTestCase):
    def test_list_users_superuser(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/user"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        # Should see at least superuser and agent
        self.assertTrue(len(response.data["results"]) >= 2)

    def test_create_user(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/user"
        data = {
            "username": "newuser",
            "password_normal": "pass123",
            "role": "AGENT",
            "project": str(self.project.uuid),
            "department": str(self.department.uuid)
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(username="newuser").count(), 1)

    def test_update_user(self):
        self.authenticate_as(self.superuser)
        url = f"/api/users/user?uuid={self.agent.uuid}"
        data = {"title": "Senior Agent"}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.title, "Senior Agent")

    def test_delete_user(self):
        self.authenticate_as(self.superuser)
        user_to_del = User.objects.create_user(username="todel", password_normal="pass123")
        url = f"/api/users/user?uuid={user_to_del.uuid}"
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(username="todel").count(), 0)
