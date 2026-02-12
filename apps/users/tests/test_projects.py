from rest_framework import status
from .base import BaseUserTestCase
from apps.users.models import Project

class ProjectTests(BaseUserTestCase):
    def test_list_projects(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/project"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Assuming pagination results format
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 1)

    def test_create_project_superuser(self):
        self.authenticate_as(self.superuser)
        url = "/api/users/project"
        from django.core.files.uploadedfile import SimpleUploadedFile
        logo = SimpleUploadedFile("logo.png", b"file_content", content_type="image/png")
        data = {"name": "New Project", "logo": logo}
        response = self.client.post(url, data, format='multipart')
        if response.status_code != 200: print(f"DEBUG Create Project: {response.data}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Project.objects.filter(name="New Project").count(), 1)

    def test_create_project_agent_denied(self):
        self.authenticate_as(self.agent)
        url = "/api/users/project"
        data = {"name": "Should Fail"}
        response = self.client.post(url, data)
        # Permissions should deny this
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # APIViewSet returns 405 if method denied or method not in allowed_methods or permission fail?
        # Actually APIViewSet seems to return 405 if method not in allowed_methods
        # and standard DRF permission check happens before wrapper.
        # Wait, APIViewSet.wrapper handles CreationFaildException etc.
        # Standard DRF permission_classes handles permission check.
        
    def test_update_project(self):
        self.authenticate_as(self.superuser)
        url = f"/api/users/project?uuid={self.project.uuid}"
        data = {"name": "Updated Name"}
        response = self.client.put(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Updated Name")

    def test_delete_project(self):
        self.authenticate_as(self.superuser)
        project_to_del = Project.objects.create(name="To Delete")
        url = f"/api/users/project?uuid={project_to_del.uuid}"
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Project.objects.filter(name="To Delete").count(), 0)
