from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import Department

class DepartmentTests(BaseUserTestCase):
    def test_list_departments(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/department"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_create_department(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/department"
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Department.objects.filter(name="New Dept").count(), 1)

    def test_update_department(self):
        self.authenticate_as(self.superuser)
        url = f"/api/users/department?uuid={self.department.uuid}"
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, "Updated Dept")
