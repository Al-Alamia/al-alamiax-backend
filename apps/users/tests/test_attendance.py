from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import ArrivingLeaving
from django.utils import timezone

class AttendanceTests(BaseUserTestCase):
    def test_arrive(self):
        self.authenticate_as(self.agent)
        url = "/api/users/arrive"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ArrivingLeaving.objects.filter(user=self.agent).count(), 1)

    def test_leave(self):
        self.authenticate_as(self.agent)
        # First arrive
        ArrivingLeaving.objects.create(user=self.agent, date=timezone.now().date(), arriving_at=timezone.now())
        
        url = "/api/users/leave"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        record = ArrivingLeaving.objects.get(user=self.agent)
        self.assertIsNotNone(record.leaving_at)

    def test_arrive_leave_details(self):
        self.authenticate_as(self.agent)
        url = "/api/users/arrive-leave-details"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_monthly_history(self):
        self.authenticate_as(self.agent)
        year = timezone.now().year
        month = timezone.now().month
        url = f"/api/users/arriving-leaving-list?user_id={self.agent.uuid}&year={year}&month={month}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
