from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import FingerPrintID

class FingerprintTests(BaseUserTestCase):
    def test_list_fingerprints(self):
        self.authenticate_as(self.agent)
        url = "/api/users/device-access"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return the fingerprint created in base.py
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 1)

    def test_create_fingerprint(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/device-access"
        data = {
            "user": str(self.agent.uuid),
            "name": "New PC",
            "unique_id": "new-device-id"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(FingerPrintID.objects.filter(unique_id="new-device-id").count(), 1)

    def test_delete_fingerprint(self):
        self.authenticate_as(self.superuser)
        url = f"/api/users/device-access?uuid={self.fingerprint.uuid}"
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(FingerPrintID.objects.filter(uuid=self.fingerprint.uuid).count(), 0)
