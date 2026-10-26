import importlib
import os
import shutil
import tempfile
from datetime import datetime

from django.apps import apps as django_apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings

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


class DeviceDedupeMigrationTests(TransactionTestCase):
    def _schema_editor(self):
        # SQLite requires FK checks off before entering the schema editor
        connection.disable_constraint_checking()
        self.addCleanup(connection.enable_constraint_checking)
        return connection.schema_editor()

    def test_duplicates_removed_keeping_oldest(self):
        mod = importlib.import_module("apps.users.migrations.0048_device_status_fields_and_approve_existing")
        user = User.objects.create_user(username="dup-user", password="x")
        other = User.objects.create_user(username="other-user", password="x")
        constraint = next(c for c in FingerPrintID._meta.constraints if c.name == "uniq_device_per_user")
        # SQLite rebuilds the table from the model's current Meta, so drop it there too
        original_constraints = FingerPrintID._meta.constraints
        FingerPrintID._meta.constraints = []
        self.addCleanup(setattr, FingerPrintID._meta, "constraints", original_constraints)
        with self._schema_editor() as editor:
            editor.remove_constraint(FingerPrintID, constraint)
        try:
            oldest = FingerPrintID.objects.create(user=user, unique_id="dup")
            newer = FingerPrintID.objects.create(user=user, unique_id="dup")
            newest = FingerPrintID.objects.create(user=user, unique_id="dup")
            unrelated = FingerPrintID.objects.create(user=other, unique_id="dup")
            for row, year in ((oldest, 2020), (newer, 2021), (newest, 2022)):
                FingerPrintID.objects.filter(pk=row.pk).update(created_at=datetime(year, 1, 1))

            mod.dedupe_devices(django_apps, None)

            remaining = FingerPrintID.objects.filter(user=user, unique_id="dup")
            self.assertEqual([d.pk for d in remaining], [oldest.pk])
            self.assertTrue(FingerPrintID.objects.filter(pk=unrelated.pk).exists())
        finally:
            FingerPrintID.objects.filter(user=user, unique_id="dup").exclude(pk=oldest.pk).delete()
            FingerPrintID._meta.constraints = original_constraints
            with self._schema_editor() as editor:
                editor.add_constraint(FingerPrintID, constraint)


class NoTelegramTokenTests(TestCase):
    def test_no_telegram_token_in_repo(self):
        root = settings.BASE_DIR
        skip = {".venv", "venv", "migrations", "node_modules", ".git", "__pycache__", "private_media", "media", "staticfiles"}
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
