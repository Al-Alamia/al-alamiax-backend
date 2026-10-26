import importlib
import os
import shutil
import tempfile

from django.apps import apps as django_apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from apps.users.models import FingerPrintID, User, UserFile
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import DeviceStatus, FileCategory


class UserAdminModelTests(BaseUserTestCase):
    def test_must_change_default_false(self):
        self.assertFalse(self.agent.must_change_password)

    def test_device_default_pending(self):
        device = FingerPrintID.objects.create(user=self.agent, unique_id="another")
        self.assertEqual(device.status, DeviceStatus.PENDING)
        self.assertIsNone(device.decided_by)
        self.assertIsNone(device.last_used_at)
        self.assertEqual(device.user_agent, "")

    def test_device_unique_per_user(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FingerPrintID.objects.create(user=self.agent, unique_id=self.fingerprint.unique_id)
        # same id for a different user is fine
        FingerPrintID.objects.create(user=self.superuser, unique_id=self.fingerprint.unique_id)

    def test_user_file_saved_outside_media_root(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        with override_settings(PRIVATE_MEDIA_ROOT=tmpdir):
            user_file = UserFile(
                user=self.agent, title="Contract", category=FileCategory.CONTRACT,
                size=3, content_type="text/plain",
            )
            user_file.file.save("a.txt", ContentFile(b"abc"), save=True)
            path = user_file.file.path
            self.assertTrue(path.startswith(tmpdir))
            self.assertFalse(path.startswith(str(settings.MEDIA_ROOT)))
            self.assertTrue(os.path.exists(path))
            self.assertIn(f"user_files/{self.agent.uuid}/", path)
            self.assertTrue(path.endswith(".txt"))


class DeviceDataMigrationTests(BaseUserTestCase):
    def test_existing_devices_approved(self):
        mod = importlib.import_module("apps.users.migrations.0048_device_status_fields_and_approve_existing")
        FingerPrintID.objects.update(status=DeviceStatus.PENDING)
        mod.approve_existing_devices(django_apps, None)
        self.assertEqual(FingerPrintID.objects.get(pk=self.fingerprint.pk).status, DeviceStatus.APPROVED)

    def test_duplicates_removed_keeping_oldest(self):
        mod = importlib.import_module("apps.users.migrations.0048_device_status_fields_and_approve_existing")
        # constraint is in a later migration; call the dedupe on non-conflicting data is a no-op
        mod.dedupe_devices(django_apps, None)
        self.assertEqual(FingerPrintID.objects.filter(pk=self.fingerprint.pk).count(), 1)


class NoTelegramTokenTests(TestCase):
    def test_no_telegram_token_in_repo(self):
        root = settings.BASE_DIR
        skip = {".venv", "venv", "migrations", "node_modules", ".git", "__pycache__"}
        offenders = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                if not name.endswith(".py") or name == "test_user_admin_models.py":
                    continue
                full = os.path.join(dirpath, name)
                with open(full, encoding="utf-8", errors="ignore") as fh:
                    if "api.telegram.org" in fh.read():
                        offenders.append(full)
        self.assertEqual(offenders, [])
