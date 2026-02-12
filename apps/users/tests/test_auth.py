from rest_framework import status
from django.urls import reverse
from .base import BaseUserTestCase

class AuthTests(BaseUserTestCase):
    def test_login_superuser(self):
        url = "/api/users/login"
        data = {
            "username": "superuser",
            "password": "pass123"
        }
        response = self.client.post(url, data, format='json')
        if response.status_code != 200: print(f"DEBUG Login Superuser: {response.data}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["username"], "superuser")

    def test_login_agent_with_device(self):
        url = "/api/users/login"
        data = {
            "username": "agent",
            "password": "pass123",
            "unique_id": "test-device-id"
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["username"], "agent")

    def test_login_agent_no_device(self):
        url = "/api/users/login"
        data = {
            "username": "agent",
            "password": "pass123"
            # unique_id missing
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["type"], "NotImplementedError")

    def test_logout(self):
        url = "/api/users/logout"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Logout successfully")
