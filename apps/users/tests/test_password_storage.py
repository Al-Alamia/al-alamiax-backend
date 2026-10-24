import json

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from tablib import Dataset

from apps.users.admin import UserResource
from apps.users.models import User
from .base import BaseUserTestCase


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for i in obj:
            yield from _keys(i)


class PasswordStorageTests(BaseUserTestCase):
    def test_create_user_hashes_password(self):
        u = User.objects.create_user(username="x", password="secret1")
        self.assertTrue(u.check_password("secret1"))
        self.assertNotEqual(u.password, "secret1")

    def test_save_does_not_rehash(self):
        self.agent.first_name = "A"
        self.agent.save()
        self.agent.refresh_from_db()
        self.assertTrue(self.agent.check_password("pass123"))

    def test_existing_hash_survives(self):
        User.objects.filter(pk=self.agent.pk).update(password=make_password("legacy1"))
        u = User.objects.get(pk=self.agent.pk)
        u.save()
        u.refresh_from_db()
        self.assertTrue(u.check_password("legacy1"))

    def test_api_create_user_hashes_password(self):
        self.authenticate_as(self.superuser)
        r = self.client.post("/api/users/user", {
            "username": "newbie", "password": "secret1",
            "project": str(self.project.uuid), "department": str(self.department.uuid),
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.get(username="newbie").check_password("secret1"))
        keys = set(_keys(json.loads(r.content)))
        self.assertNotIn("password", keys)
        self.assertNotIn("password_normal", keys)

    def test_update_user_keeps_password(self):
        self.authenticate_as(self.superuser)
        r = self.client.put(f"/api/users/user?uuid={self.agent.uuid}",
                            {"title": "Senior Agent", "password": "hacked1"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.title, "Senior Agent")
        self.assertTrue(self.agent.check_password("pass123"))

    def test_user_list_has_no_passwords(self):
        self.authenticate_as(self.superuser)
        r = self.client.get("/api/users/user")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("password_normal", r.content.decode())
        self.assertNotIn("pbkdf2", r.content.decode())

    def test_send_password_removed(self):
        r = self.client.post("/api/users/send_password")
        self.assertEqual(r.status_code, 404)

    def test_admin_add_and_password_pages(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("admin:users_user_add")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("admin:auth_user_password_change", args=[self.agent.pk])).status_code, 200)
        r = self.client.post(reverse("admin:users_user_add"), {
            "username": "adm1", "password1": "Secret12!x", "password2": "Secret12!x"})
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(User.objects.get(username="adm1").check_password("Secret12!x"))

    def test_import_hashes_password_and_export_omits_it(self):
        ds = Dataset(headers=["username", "password"])
        ds.append(("imp1", "secret1"))
        res = UserResource().import_data(ds)
        self.assertFalse(res.has_errors(), [r.traceback for row in res.row_errors() for r in row[1]])
        self.assertTrue(User.objects.get(username="imp1").check_password("secret1"))
        headers = UserResource().export(queryset=User.objects.all()).headers
        self.assertNotIn("password", headers)
        self.assertNotIn("password_normal", headers)
