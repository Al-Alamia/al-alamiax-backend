import io
import os
import shutil
import tempfile
import zipfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.users.models import Department, UserFile
from apps.users.types import UserTypes
from .base import BaseUserTestCase
from .user_admin_factories import make_user

PDF = b"%PDF-1.4\n" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def docx_bytes(member="word/document.xml"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, "<x/>")
    return buf.getvalue()


def upload(name, content):
    return SimpleUploadedFile(name, content)


class UserFilesApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.private, self.media = tempfile.mkdtemp(), tempfile.mkdtemp()
        override = override_settings(PRIVATE_MEDIA_ROOT=self.private, MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.private, True)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.other_dept = Department.objects.create(name="Other")
        self.hr = make_user("hr1", UserTypes.HR)
        self.manager = make_user("mgr1", UserTypes.MANAGER, department=self.department)
        self.other_manager = make_user("mgr2", UserTypes.MANAGER, department=self.other_dept)
        self.peer = make_user("peer", UserTypes.AGENT, department=self.department)

    def url(self, user):
        return f"/api/users/admin/users/{user.uuid}/files"

    def post(self, user, name="doc.pdf", content=PDF, title="Contract", category="contract"):
        return self.client.post(self.url(user), {"title": title, "category": category,
                                                 "file": upload(name, content)}, format="multipart")

    def make_file(self):
        self.authenticate_as(self.hr)
        return UserFile.objects.get(uuid=self.post(self.agent).data["uuid"])

    def test_upload_ok(self):
        self.authenticate_as(self.hr)
        r = self.post(self.agent)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(set(r.data), {"uuid", "title", "category", "size", "content_type", "created_at",
                                       "uploaded_by", "can"})
        self.assertEqual((r.data["size"], r.data["content_type"]), (len(PDF), "application/pdf"))
        self.assertEqual(r.data["uploaded_by"]["uuid"], str(self.hr.uuid))
        self.assertTrue(r.data["can"]["delete"])
        f = UserFile.objects.get(uuid=r.data["uuid"])
        self.assertTrue(f.file.name.endswith(".pdf"))
        self.assertTrue(os.path.exists(f.file.path))

    def test_stored_extension_from_detected_type(self):
        self.authenticate_as(self.hr)
        r = self.post(self.agent, "photo.JPEG", b"\xff\xd8\xff\xe0" + b"0" * 8)
        self.assertEqual((r.status_code, r.data["content_type"]), (201, "image/jpeg"))
        self.assertTrue(UserFile.objects.get(uuid=r.data["uuid"]).file.name.endswith(".jpg"))

    def test_docx_ok_and_fake_docx_rejected(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.post(self.agent, "a.docx", docx_bytes()).status_code, 201)
        for name, content in (("a.docx", docx_bytes("other.xml")), ("a.docx", b"PK\x03\x04junk"),
                              ("a.zip", docx_bytes())):
            r = self.post(self.agent, name, content)
            self.assertEqual((r.status_code, r.data["type"]), (400, "file_type"), name)

    def test_too_large(self):
        self.authenticate_as(self.hr)
        r = self.post(self.agent, "big.pdf", b"%PDF" + b"0" * (10 * 1024 * 1024 - 3))
        self.assertEqual((r.status_code, r.data["type"]), (400, "file_too_large"))
        self.assertEqual(UserFile.objects.count(), 0)

    def test_exact_limit_ok(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.post(self.agent, "ok.pdf", b"%PDF" + b"0" * (10 * 1024 * 1024 - 4)).status_code, 201)

    def test_bad_types(self):
        self.authenticate_as(self.hr)
        for name, content in (("a.pdf", PNG), ("a.exe", b"MZ" + b"0" * 20), ("a.exe", PDF), ("a.png", PDF)):
            r = self.post(self.agent, name, content)
            self.assertEqual((r.status_code, r.data["type"]), (400, "file_type"), name)

    def test_validation(self):
        self.authenticate_as(self.hr)
        for kw in ({"title": " "}, {"category": "bogus"}, {"title": "x" * 151}):
            self.assertEqual(self.post(self.agent, **kw).data["type"], "invalid", kw)
        r = self.client.post(self.url(self.agent), {"title": "t", "category": "id"}, format="multipart")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_file_not_under_media_root(self):
        f = self.make_file()
        self.assertFalse(os.path.abspath(f.file.path).startswith(os.path.abspath(settings.MEDIA_ROOT)))
        self.assertTrue(os.path.abspath(f.file.path).startswith(os.path.abspath(settings.PRIVATE_MEDIA_ROOT)))
        self.assertEqual(self.client.get("/media/" + f.file.name).status_code, 404)

    def test_list_authz(self):
        f = self.make_file()
        for who, status in ((self.agent, 200), (self.hr, 200), (self.manager, 200),
                            (self.other_manager, 404), (self.peer, 404)):
            self.authenticate_as(who)
            self.assertEqual(self.client.get(self.url(self.agent)).status_code, status, who.username)
        self.authenticate_as(self.agent)
        r = self.client.get(self.url(self.agent))
        self.assertEqual([x["uuid"] for x in r.data], [str(f.uuid)])
        self.assertFalse(r.data[0]["can"]["delete"])

    def test_download(self):
        f = self.make_file()
        for who in (self.agent, self.manager, self.hr):
            self.authenticate_as(who)
            r = self.client.get(f"/api/users/files/{f.uuid}/download")
            self.assertEqual(r.status_code, 200, who.username)
            self.assertEqual(b"".join(r.streaming_content), PDF)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertEqual(r["X-Content-Type-Options"], "nosniff")
            self.assertIn('attachment; filename="Contract.pdf"', r["Content-Disposition"])
        for who in (self.other_manager, self.peer):
            self.authenticate_as(who)
            self.assertEqual(self.client.get(f"/api/users/files/{f.uuid}/download").status_code, 404)

    def test_download_exposes_content_disposition_cross_origin(self):
        f = self.make_file()
        self.authenticate_as(self.hr)
        r = self.client.get(f"/api/users/files/{f.uuid}/download", HTTP_ORIGIN="http://localhost:3000")
        self.assertIn("content-disposition", r["Access-Control-Expose-Headers"].lower())

    def test_download_filename_sanitized(self):
        self.authenticate_as(self.hr)
        uuid = self.post(self.agent, title='../../a"b\r\nc').data["uuid"]
        r = self.client.get(f"/api/users/files/{uuid}/download")
        disposition = r["Content-Disposition"]
        self.assertNotIn("/", disposition)
        self.assertNotIn("\n", disposition)
        self.assertTrue(disposition.endswith('.pdf"'), disposition)

    def test_upload_requires_manage(self):
        self.authenticate_as(self.manager)
        r = self.post(self.agent)
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        self.authenticate_as(self.agent)
        self.assertEqual(self.post(self.agent).status_code, 403)
        self.authenticate_as(self.other_manager)
        self.assertEqual(self.post(self.agent).status_code, 404)
        self.assertEqual(UserFile.objects.count(), 0)

    def test_delete_removes_stored_file(self):
        f = self.make_file()
        path = f.file.path
        self.authenticate_as(self.manager)
        r = self.client.delete(f"/api/users/files/{f.uuid}")
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        self.assertTrue(os.path.exists(path))
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.delete(f"/api/users/files/{f.uuid}").status_code, 204)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(UserFile.objects.filter(pk=f.pk).exists())

    def test_delete_invisible_404(self):
        f = self.make_file()
        self.authenticate_as(self.other_manager)
        self.assertEqual(self.client.delete(f"/api/users/files/{f.uuid}").status_code, 404)
        self.assertTrue(UserFile.objects.filter(pk=f.pk).exists())

    def test_me_files(self):
        self.make_file()
        self.authenticate_as(self.hr)
        self.post(self.hr, title="Mine")
        r = self.client.get("/api/users/me/files")
        self.assertEqual([x["title"] for x in r.data], ["Mine"])
        self.authenticate_as(self.agent)
        self.assertEqual([x["title"] for x in self.client.get("/api/users/me/files").data], ["Contract"])
