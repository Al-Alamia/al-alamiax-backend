import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.users.tests.test_must_change import LOGIN
from .base import BaseUserTestCase

URL = "/api/users/me/profile"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


class ProfileApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.authenticate_as(self.agent)

    def test_get_shape(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"phone", "picture", "telegram_id", "about", "user"})
        self.assertEqual(r.data["user"]["username"], "agent")
        self.assertEqual(r.data["user"]["department"]["name"], "Test Department")
        self.assertIsNone(r.data["picture"])

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_patch_self_multipart(self):
        r = self.client.patch(URL, {"about": "I am an agent", "phone": "01012345678", "telegram_id": "123"})
        self.assertEqual(r.status_code, 200, r.data)
        self.agent.profile.refresh_from_db()
        self.assertEqual((self.agent.profile.about, self.agent.profile.phone, self.agent.profile.telegram_id),
                         ("I am an agent", "01012345678", 123))

    def test_patch_json_and_clear(self):
        self.client.patch(URL, {"telegram_id": 5}, format="json")
        r = self.client.patch(URL, {"telegram_id": "", "phone": ""}, format="json")
        self.assertEqual((r.status_code, r.data["telegram_id"], r.data["phone"]), (200, None, None))

    def test_read_only_fields_ignored(self):
        r = self.client.patch(URL, {"about": "x", "user": "evil", "role": "OWNER", "username": "hacker"})
        self.assertEqual(r.status_code, 200)
        self.agent.refresh_from_db()
        self.assertEqual((self.agent.role, self.agent.username), ("AGENT", "agent"))

    def test_bad_phone_invalid(self):
        r = self.client.patch(URL, {"phone": "123"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        self.assertIn("Number", r.data["message"])

    def test_bad_telegram_invalid(self):
        for bad in ("abc", "-3", "0", "²"):
            r = self.client.patch(URL, {"telegram_id": bad})
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), bad)

    def test_picture_formats_accepted(self):
        for name, data in (("a.jpg", JPEG), ("a.png", PNG), ("a.webp", WEBP)):
            r = self.client.patch(URL, {"picture": SimpleUploadedFile(name, data)}, format="multipart")
            self.assertEqual(r.status_code, 200, name)
            self.assertTrue(r.data["picture"])

    def test_picture_too_large(self):
        big = SimpleUploadedFile("a.png", PNG + b"\x00" * (5 * 1024 * 1024))
        r = self.client.patch(URL, {"picture": big}, format="multipart")
        self.assertEqual((r.status_code, r.data["type"]), (400, "file_too_large"))

    def test_picture_wrong_type(self):
        r = self.client.patch(URL, {"picture": SimpleUploadedFile("a.png", b"not an image at all")},
                              format="multipart")
        self.assertEqual((r.status_code, r.data["type"]), (400, "file_type"))
        self.agent.profile.refresh_from_db()
        self.assertFalse(self.agent.profile.picture)

    def test_invalid_picture_does_not_save_other_fields(self):
        self.client.patch(URL, {"about": "keep", "picture": SimpleUploadedFile("a.png", b"junk")},
                          format="multipart")
        self.agent.profile.refresh_from_db()
        self.assertEqual(self.agent.profile.about, "")

    def test_old_profile_route_gone(self):
        self.assertEqual(self.client.get("/api/users/profile").status_code, 404)

    def test_must_change_user_can_get_but_not_patch(self):
        self.agent.must_change_password = True
        self.agent.save()
        self.client.force_authenticate(user=None)
        res = self.client.post(LOGIN, {"username": "agent", "password": "pass123",
                                       "unique_id": "test-device-id"}, format="json")
        auth = {"HTTP_AUTHORIZATION": f"Bearer {res.data['Authorization']}"}
        self.assertEqual(self.client.get(URL, **auth).status_code, 200)
        r = self.client.patch(URL, {"about": "x"}, format="json", **auth)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["type"], "password_change_required")
