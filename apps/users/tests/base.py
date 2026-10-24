from rest_framework.test import APITestCase
from django.db.models.signals import post_save, post_delete
from apps.users.models import User, Project, Department, fp_signal, fp_delete
from apps.users.types import UserTypes

class BaseUserTestCase(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # ZK fingerprint device is unreachable in tests
        post_save.disconnect(fp_signal, sender=User)
        post_delete.disconnect(fp_delete, sender=User)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(fp_signal, sender=User)
        post_delete.connect(fp_delete, sender=User)
        super().tearDownClass()

    def setUp(self):
        # Create default project and department
        self.project = Project.objects.create(name="Test Project")
        self.department = Department.objects.create(name="Test Department")

        # Create superuser
        self.superuser = User.objects.create_superuser(
            username="superuser",
            password="pass123",
            email="super@test.com",
            role=UserTypes.OWNER, # Or whatever is highest
            project=self.project,
            department=self.department
        )

        # Create normal agent
        self.agent = User.objects.create_user(
            username="agent",
            password="pass123",
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
