from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import ReportRecord
from django.utils import timezone

class ReportTests(BaseUserTestCase):
    def test_add_report(self):
        self.authenticate_as(self.agent)
        url = "/api/users/add-report"
        data = {"key": "value", "another": 123}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ReportRecord.objects.filter(user=self.agent).count(), 1)

    def test_check_report(self):
        self.authenticate_as(self.agent)
        url = "/api/users/check-report"
        # Initially can report
        response = self.client.get(url)
        self.assertEqual(response.data["canReport"], True)
        
        # Add a report
        ReportRecord.objects.create(user=self.agent, date=timezone.now().date(), json_data='{}')
        
        # Now cannot report
        response = self.client.get(url)
        self.assertEqual(response.data["canReport"], False)

    def test_get_reports(self):
        self.authenticate_as(self.superuser)
        # Create a report record manually
        ReportRecord.objects.create(user=self.agent, date=timezone.now().date(), json_data='{"test":1}')
        
        url = f"/api/users/get-reports?project={self.project.uuid}&date={timezone.now().date().strftime('%Y-%m-%d')}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 1)
