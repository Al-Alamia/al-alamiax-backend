from rest_framework.test import APITestCase
from apps.users.models import User, Project, Department
from apps.users.types import UserTypes

class BaseUserTestCase(APITestCase):
    def setUp(self):
        # Create default project and department
        self.project = Project.objects.create(name="Test Project")
        self.department = Department.objects.create(name="Test Department")

        # Create superuser
        self.superuser = User.objects.create_superuser(
            username="superuser",
            password_normal="pass123",
            email="super@test.com",
            role=UserTypes.OWNER, # Or whatever is highest
            project=self.project,
            department=self.department
        )

        # Create normal agent
        self.agent = User.objects.create_user(
            username="agent",
            password_normal="pass123",
            email="agent@test.com",
            role=UserTypes.AGENT,
            project=self.project,
            department=self.department
        )
        
        from apps.users.models import FingerPrintID
        self.fingerprint = FingerPrintID.objects.create(
            user=self.agent,
            unique_id="test-device-id",
            name="Test PC"
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)
