import datetime
import uuid
from datetime import datetime as dt, timedelta

from django.test import override_settings

from apps.attendance.models import AttendanceDay, Punch, WebPunchPolicy
from apps.attendance.tests.factories import assign, make_shift, punch
from apps.attendance.types import PunchSource
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

PUNCH = "/api/attendance/punch"
TODAY = "/api/attendance/today"
PUNCHES = "/api/attendance/punches"


class WebPunchTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate_as(self.agent)

    def test_punch_creates_web_punch(self):
        r = self.client.post(PUNCH, {"unique_id": "test-device-id"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["punches"]), 1)
        p = r.data["punches"][0]
        self.assertEqual(p["source"], "WEB")
        self.assertEqual(p["device_id"], "test-device-id")
        self.assertIsNone(p["device_name"])
        self.assertEqual(Punch.objects.get().timestamp.microsecond, 0)

    def test_second_punch_within_60s_is_409(self):
        self.client.post(PUNCH, {}, format="json")
        r = self.client.post(PUNCH, {}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["type"], "too_soon")

    def test_throttle_counts_any_source(self):
        punch(self.agent, dt.now() - timedelta(seconds=10), source=PunchSource.MANUAL)
        self.assertEqual(self.client.post(PUNCH, {}, format="json").status_code, 409)

    def test_trusted_device(self):
        WebPunchPolicy.objects.create(department=self.department, require_trusted_device=True)
        r = self.client.post(PUNCH, {"unique_id": "nope"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (403, "untrusted_device"))
        r = self.client.post(PUNCH, {}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.client.post(PUNCH, {"unique_id": "test-device-id"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_office_ip(self):
        WebPunchPolicy.objects.create(department=self.department, require_office_ip=True,
                                      allowed_ips=["10.0.0.0/8"])
        r = self.client.post(PUNCH, {}, format="json", REMOTE_ADDR="127.0.0.1")
        self.assertEqual((r.status_code, r.data["type"]), (403, "ip_not_allowed"))
        r = self.client.post(PUNCH, {}, format="json", REMOTE_ADDR="10.1.2.3")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["punches"][0]["ip"], "10.1.2.3")

    def test_forwarded_for_ignored_unless_trusted(self):
        WebPunchPolicy.objects.create(department=self.department, require_office_ip=True,
                                      allowed_ips=["10.0.0.0/8"])
        r = self.client.post(PUNCH, {}, format="json", REMOTE_ADDR="127.0.0.1",
                             HTTP_X_FORWARDED_FOR="10.1.2.3")
        self.assertEqual(r.status_code, 403)
        with override_settings(ATTENDANCE_TRUST_PROXY=True):
            r = self.client.post(PUNCH, {}, format="json", REMOTE_ADDR="127.0.0.1",
                                 HTTP_X_FORWARDED_FOR="10.1.2.3, 5.5.5.5")
        self.assertEqual(r.status_code, 200)

    def test_punch_evaluates_the_owning_day(self):
        assign(make_shift(weekend_days=[]), department=self.department,
               effective_from=datetime.date(2020, 1, 1))
        r = self.client.post(PUNCH, {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["day"]["date"], r.data["date"])
        self.assertTrue(AttendanceDay.objects.filter(user=self.agent, date=r.data["date"]).exists())


class TodayTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate_as(self.agent)

    def test_no_shift(self):
        r = self.client.get(TODAY)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["shift"])
        self.assertTrue(r.data["can_punch"])
        self.assertIsNone(r.data["blocked_reason"])
        self.assertEqual(r.data["date"], dt.now().date().isoformat())
        self.assertEqual(r.data["punches"], [])

    def test_blocked(self):
        WebPunchPolicy.objects.create(department=self.department, require_trusted_device=True)
        r = self.client.get(TODAY, {"unique_id": "nope"})
        self.assertFalse(r.data["can_punch"])
        self.assertEqual(r.data["blocked_reason"], "untrusted_device")
        r = self.client.get(TODAY, {"unique_id": "test-device-id"})
        self.assertTrue(r.data["can_punch"])

    def test_shift_payload(self):
        assign(make_shift(name="Day"), department=self.department, effective_from=datetime.date(2020, 1, 1))
        r = self.client.get(TODAY)
        self.assertEqual(r.data["shift"]["name"], "Day")
        self.assertEqual(r.data["shift"]["expected_start"], "09:00")
        self.assertEqual(r.data["shift"]["expected_end"], "17:00")
        self.assertEqual(r.data["shift"]["grace_minutes"], 10)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(TODAY).status_code, (401, 403))


class PunchesApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        from apps.users.models import Department
        self.other_dept = Department.objects.create(name="Other")
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR,
                                           department=self.other_dept)
        self.manager = User.objects.create_user(username="mgr", password="x", role=UserTypes.MANAGER,
                                                department=self.department)
        self.other_mgr = User.objects.create_user(username="mgr2", password="x", role=UserTypes.MANAGER,
                                                  department=self.other_dept)
        self.past = (dt.now() - timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        self.body = {"user": str(self.agent.uuid), "timestamp": self.past.strftime("%Y-%m-%dT%H:%M"),
                     "note": "forgot"}

    def test_hr_creates_manual(self):
        self.authenticate_as(self.hr)
        r = self.client.post(PUNCHES, self.body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["source"], "MANUAL")
        self.assertEqual(r.data["created_by"], "hr")
        self.assertEqual(r.data["note"], "forgot")
        self.assertEqual(r.data["timestamp"], self.past.strftime("%Y-%m-%dT%H:%M:%S"))
        self.assertEqual(r.data["user"], str(self.agent.uuid))

    def test_create_validation(self):
        self.authenticate_as(self.hr)
        for patch in ({"note": ""}, {"note": None}, {"timestamp": "garbage"},
                      {"timestamp": (dt.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")},
                      {"timestamp": None}):
            r = self.client.post(PUNCHES, {**self.body, **patch}, format="json")
            self.assertEqual(r.status_code, 400, patch)
            self.assertIn("type", r.data)
        bad = self.client.post(PUNCHES, {**self.body, "user": "nope"}, format="json")
        self.assertEqual((bad.status_code, bad.data["type"]), (400, "invalid_user"))
        unk = self.client.post(PUNCHES, {**self.body, "user": str(uuid.uuid4())}, format="json")
        self.assertEqual((unk.status_code, unk.data["type"]), (400, "invalid_user"))

    def test_roles(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.post(PUNCHES, self.body, format="json").status_code, 403)
        self.authenticate_as(self.other_mgr)
        r = self.client.post(PUNCHES, self.body, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.post(PUNCHES, self.body, format="json").status_code, 201)

    def test_delete(self):
        web = punch(self.agent, self.past, PunchSource.WEB)
        man = punch(self.agent, self.past + timedelta(hours=1), PunchSource.MANUAL)
        self.authenticate_as(self.hr)
        r = self.client.delete(f"{PUNCHES}/{web.uuid}")
        self.assertEqual((r.status_code, r.data["type"]), (400, "not_manual"))
        self.assertEqual(self.client.delete(f"{PUNCHES}/{man.uuid}").status_code, 204)
        self.assertFalse(Punch.objects.filter(uuid=man.uuid).exists())
        self.assertEqual(self.client.delete(f"{PUNCHES}/{uuid.uuid4()}").status_code, 404)
        self.authenticate_as(self.other_mgr)
        man2 = punch(self.agent, self.past + timedelta(hours=2), PunchSource.MANUAL)
        self.assertEqual(self.client.delete(f"{PUNCHES}/{man2.uuid}").status_code, 403)
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.delete(f"{PUNCHES}/{man2.uuid}").status_code, 403)

    def test_delete_reevaluates_day(self):
        assign(make_shift(weekend_days=[]), department=self.department,
               effective_from=datetime.date(2020, 1, 1))
        self.authenticate_as(self.hr)
        r = self.client.post(PUNCHES, self.body, format="json")
        d = self.past.date()
        self.assertEqual(AttendanceDay.objects.get(user=self.agent, date=d).status, "INCOMPLETE")
        self.client.delete(f"{PUNCHES}/{r.data['uuid']}")
        self.assertEqual(AttendanceDay.objects.get(user=self.agent, date=d).status, "ABSENT")

    def test_list_scope(self):
        punch(self.agent, self.past)
        date = self.past.date().isoformat()
        url = lambda u: f"{PUNCHES}?user={u}&date={date}"
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(url(self.superuser.uuid)).status_code, 403)
        self.assertEqual(self.client.get(url(self.agent.uuid)).status_code, 200)
        self.authenticate_as(self.manager)
        r = self.client.get(url(self.agent.uuid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
        self.authenticate_as(self.other_mgr)
        self.assertEqual(self.client.get(url(self.agent.uuid)).status_code, 403)
        r = self.client.get(url("not-a-uuid"))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_user"))
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get(f"{PUNCHES}?user={self.agent.uuid}&date=zz").status_code, 400)

    def test_list_ordered_and_night_owned(self):
        night = make_shift(start_time=datetime.time(22), end_time=datetime.time(6), weekend_days=[])
        assign(night, department=self.department, effective_from=datetime.date(2020, 1, 1))
        d = datetime.date(2026, 9, 14)
        late = punch(self.agent, dt(2026, 9, 14, 23, 0))
        early = punch(self.agent, dt(2026, 9, 14, 21, 50))
        morning = punch(self.agent, dt(2026, 9, 15, 5, 50))      # belongs to Sep 14
        next_day = punch(self.agent, dt(2026, 9, 15, 21, 55))     # belongs to Sep 15
        self.authenticate_as(self.hr)
        r = self.client.get(f"{PUNCHES}?user={self.agent.uuid}&date={d}")
        self.assertEqual([p["uuid"] for p in r.data],
                         [str(early.uuid), str(late.uuid), str(morning.uuid)])
        r = self.client.get(f"{PUNCHES}?user={self.agent.uuid}&date=2026-09-15")
        self.assertEqual([p["uuid"] for p in r.data], [str(next_day.uuid)])

    def test_list_no_shift_calendar_day(self):
        a = punch(self.agent, dt(2026, 9, 14, 0, 5))
        punch(self.agent, dt(2026, 9, 13, 23, 55))
        self.authenticate_as(self.hr)
        r = self.client.get(f"{PUNCHES}?user={self.agent.uuid}&date=2026-09-14")
        self.assertEqual([p["uuid"] for p in r.data], [str(a.uuid)])
