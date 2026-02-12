from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import Request
from django.utils import timezone

class RequestTests(BaseUserTestCase):
    def test_create_request(self):
        self.authenticate_as(self.agent)
        url = "/api/users/request"
        data = {
            "user": str(self.agent.uuid),
            "details": "Test request details",
            "type": "GLOBAL",
            "date": timezone.now().date().strftime("%Y-%m-%d")
        }
        # RequestAPI uses MultiDateFormatField which supports %Y-%m-%d
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Request.objects.count(), 1)

    def test_list_requests(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/request"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
