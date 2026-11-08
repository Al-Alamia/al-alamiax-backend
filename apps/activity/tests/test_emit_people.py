import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.activity.models import ActivityEvent
from apps.attendance.services import requests as svc
from apps.attendance.tests.test_request_service import D, RequestServiceBase
from apps.attendance.types import RequestKind as K
from apps.penalties.services import create_penalty, void_penalty
from apps.penalties.tests.factories import make_user as make_penalty_user
from apps.penalties.types import PenaltyKind
from apps.users.services import devices, files, users as user_svc
from apps.users.tests.base import BaseUserTestCase
from apps.users.tests.user_admin_factories import make_device, make_user
from apps.users.types import UserTypes


class RequestEventTests(RequestServiceBase):
    def one(self, verb):
        qs = ActivityEvent.objects.filter(verb=verb)
        self.assertEqual(qs.count(), 1, verb)
        return qs.get()

    def check(self, verb, actor, subject):
        e = self.one(verb)
        self.assertEqual((e.actor, e.subject), (actor, subject))
        self.assertEqual(e.area, "attendance")
        return e

    def test_request_lifecycle_events(self):
        req = self.leave()
        e = self.check("request.submitted", self.agent, self.agent)
        self.assertEqual(e.data["start_date"], "2026-11-02")
        self.assertEqual(e.target_uuid, req.pk)
        svc.approve(self.manager, req, "ok")
        e = self.check("request.approved", self.manager, self.agent)
        self.assertEqual(e.data["note"], "ok")
        self.assertIn("2026-11-02", e.target_label)

        svc.revoke(self.hr, req, "mistake")
        self.check("request.revoked", self.hr, self.agent)

        r2 = self.leave(D(2026, 11, 9))
        svc.reject(self.manager, r2, "no")
        self.check("request.rejected", self.manager, self.agent)

        r3 = self.leave(D(2026, 11, 16))
        svc.cancel(self.agent, r3)
        self.check("request.cancelled", self.agent, self.agent)

    def test_request_edit_event(self):
        req = self.leave()
        svc.edit(self.agent, req, {"end_date": D(2026, 11, 3)})
        e = self.check("request.edited", self.agent, self.agent)
        self.assertEqual(e.data["end_date"], "2026-11-03")

    def test_failed_action_emits_nothing(self):
        req = self.leave()
        with self.assertRaises(Exception):
            svc.revoke(self.hr, req, "x")  # pending, cannot revoke
        self.assertFalse(ActivityEvent.objects.filter(verb="request.revoked").exists())


class PenaltyEventTests(BaseUserTestCase):
    def test_penalty_create_void(self):
        hr = make_penalty_user("hr", UserTypes.HR, self.department)
        p = create_penalty(hr, {"user": self.agent, "penalty_type": None, "title": "Late",
                                "kind": PenaltyKind.DAYS, "value": Decimal("0.5"), "description": "",
                                "date": date.today()})
        e = ActivityEvent.objects.get(verb="penalty.created")
        self.assertEqual((e.actor, e.subject, e.target_label, e.area), (hr, self.agent, "Late", "attendance"))
        self.assertEqual(e.data["value"], "0.5")
        void_penalty(hr, p, "mistake")
        e = ActivityEvent.objects.get(verb="penalty.voided")
        self.assertEqual((e.actor, e.subject, e.target_label), (hr, self.agent, "Late"))


class UserEventTests(BaseUserTestCase):
    def test_user_create_update_deactivate_activate(self):
        hr = make_user("hr1", UserTypes.HR)
        u = user_svc.create_user(hr, {"username": "newbie", "password": "Str0ng-Pass!9x",
                                      "first_name": "New", "last_name": "Bie"})
        e = ActivityEvent.objects.get(verb="user.created")
        self.assertEqual((e.actor, e.subject, e.target_label), (hr, u, "New Bie"))

        user_svc.update_user(hr, u, {"first_name": "Newer", "last_name": "Bie", "password": "secret"})
        e = ActivityEvent.objects.get(verb="user.updated")
        self.assertEqual(e.data, {"fields": ["first_name"]})
        self.assertNotIn("password", str(e.data))

        user_svc.set_active(hr, u, False)
        e = ActivityEvent.objects.get(verb="user.deactivated")
        self.assertEqual((e.actor, e.subject), (hr, u))
        user_svc.set_active(hr, u, True)
        self.assertEqual(ActivityEvent.objects.get(verb="user.activated").subject, u)


class DeviceEventTests(BaseUserTestCase):
    def test_device_approve_reject_revoke(self):
        hr = make_user("hr1", UserTypes.HR)
        d1 = make_device(self.agent, "a", status="pending")
        d2 = make_device(self.agent, "b", status="pending")
        d1.name, d2.name = "Phone", "Laptop"
        d1.save(), d2.save()
        devices.approve_device(hr, d1)
        devices.reject_device(hr, d2)
        devices.revoke_device(hr, d1)
        for verb, name in (("approved", "Phone"), ("rejected", "Laptop"), ("revoked", "Phone")):
            e = ActivityEvent.objects.get(verb=f"device.{verb}")
            self.assertEqual((e.actor, e.subject, e.target_label, e.area), (hr, self.agent, name, "people"))


class FileEventTests(BaseUserTestCase):
    def test_file_upload_delete(self):
        private, media = tempfile.mkdtemp(), tempfile.mkdtemp()
        ov = override_settings(PRIVATE_MEDIA_ROOT=private, MEDIA_ROOT=media)
        ov.enable()
        self.addCleanup(ov.disable)
        self.addCleanup(shutil.rmtree, private, True)
        self.addCleanup(shutil.rmtree, media, True)
        hr = make_user("hr1", UserTypes.HR)
        f = files.save_user_file(hr, self.agent, "Contract", "contract",
                                 SimpleUploadedFile("doc.pdf", b"%PDF-1.4\n" + b"0" * 32))
        e = ActivityEvent.objects.get(verb="file.uploaded")
        self.assertEqual((e.actor, e.subject, e.target_label), (hr, self.agent, "Contract"))
        files.delete_user_file(hr, f)
        e = ActivityEvent.objects.get(verb="file.deleted")
        self.assertEqual((e.actor, e.subject, e.target_label), (hr, self.agent, "Contract"))
