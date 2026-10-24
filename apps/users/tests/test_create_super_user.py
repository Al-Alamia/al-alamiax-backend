from io import StringIO

from django.contrib.auth import authenticate
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.users.models import User


class CreateSuperUserCommandTests(TestCase):
    def test_creates_superuser_who_can_authenticate(self):
        out = StringIO()
        call_command(
            "create_super_user", username="root1", email="root1@example.com",
            password="s3cret-pw", stdout=out,
        )
        user = User.objects.get(username="root1")
        self.assertTrue(user.is_superuser)
        self.assertIn(str(user.pk), out.getvalue())
        self.assertIsNotNone(authenticate(username="root1", password="s3cret-pw"))

    def test_password_required(self):
        with self.assertRaises(CommandError):
            call_command("create_super_user", "--username=x", "--email=x@example.com")
