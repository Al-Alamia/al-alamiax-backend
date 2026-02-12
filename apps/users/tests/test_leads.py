from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import Lead, User
import pandas as pd
import io
from django.core.files.uploadedfile import SimpleUploadedFile

class LeadTests(BaseUserTestCase):
    def test_create_lead(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/lead"
        data = {
            "user": str(self.agent.uuid),
            "phone": "01234567890",
            "name": "Test Lead",
            "date": "2024-01-01T12:00:00Z",
            "project": str(self.project.uuid)
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Lead.objects.filter(phone="01234567890").count(), 1)

    def test_user_leads_summary(self):
        self.authenticate_as(self.agent)
        from django.utils import timezone
        url = f"/api/users/user-leads?user_uuid={self.agent.uuid}&month={timezone.now().month}&year={timezone.now().year}"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("total", response.data)

    def test_upload_sheet_mock(self):
        self.authenticate_as(self.agent)
        self.agent.crm_username = "test_crm"
        self.agent.save()
        
        # Create a mock Excel file
        df = pd.DataFrame({
            "Market": ["test_crm"],
            "Phone": ["01111111111"],
            "Date": ["2024-01-01 - 12:00"]
        })
        excel_file = io.BytesIO()
        df.to_excel(excel_file, index=False)
        excel_file.seek(0)
        
        uploaded_file = SimpleUploadedFile("test.xlsx", excel_file.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        url = "/api/users/upload-sheet"
        response = self.client.post(url, {"file": uploaded_file}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_count"], 1)
