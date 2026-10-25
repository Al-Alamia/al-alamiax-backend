import datetime as dt
from unittest import mock

from apps.attendance.models import LeaveAllowance, LeaveType
from apps.attendance.tests.factories import assign, make_leave_type, make_policy, make_request, make_shift
from apps.attendance.types import RequestKind as K
from apps.attendance.views import leave
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = dt.date
BASE = "/api/attendance"
TYPES, ALLOW = f"{BASE}/leave-types", f"{BASE}/leave-allowances"
BAL, WD = f"{BASE}/leave-balances", f"{BASE}/leave-working-days"
TYPE_BODY = {"name": "Sick", "pay_percent": 50, "uses_balance": True, "yearly_allowance": 10,
             "requires_attachment": False, "is_active": True}


class LeaveApiBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(leave, "_now", return_value=dt.datetime(2026, 10, 25, 12))
        patcher.start()
        self.addCleanup(patcher.stop)
        make_policy()
        assign(make_shift(weekend_days=[4, 5]), department=self.department)
        self.other_dept = Department.objects.create(name="Other")
        assign(make_shift(), department=self.other_dept)
        self.manager = self.mk("manager", UserTypes.MANAGER)
        self.hr = self.mk("hr", UserTypes.HR)
        self.outsider = self.mk("outsider", UserTypes.AGENT, self.other_dept)
        self.annual = make_leave_type(name="Annual", uses_balance=True, yearly_allowance=21)

    def mk(self, name, role, dept=None):
        u = User.objects.create_user(username=name, password="x", email=f"{name}@t.com", role=role,
                                     project=self.project, department=dept or self.department)
        User.objects.filter(pk=u.pk).update(date_joined=dt.datetime(2020, 1, 1))
        u.refresh_from_db()
        return u


class LeaveTypeTests(LeaveApiBase):
    def test_agent_sees_active_types_only(self):
        make_leave_type(name="Old", is_active=False)
        self.authenticate_as(self.agent)
        names = [t["name"] for t in self.client.get(TYPES).data]
        self.assertEqual(names, ["Annual"])
        self.authenticate_as(self.hr)
        self.assertEqual(len(self.client.get(TYPES).data), 2)

    def test_agent_cannot_create_type(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.post(TYPES, TYPE_BODY, format="json").status_code, 403)

    def test_hr_crud(self):
        self.authenticate_as(self.hr)
        res = self.client.post(TYPES, TYPE_BODY, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["yearly_allowance"], 10)
        self.assertEqual(res.data["pay_percent"], 50)
        url = f"{TYPES}/{res.data['uuid']}"
        res = self.client.patch(url, {"pay_percent": 80, "is_active": False}, format="json")
        self.assertEqual((res.status_code, res.data["pay_percent"], res.data["is_active"]), (200, 80, False))
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_inactive_type_detail_hidden_from_agent(self):
        t = make_leave_type(name="Old", is_active=False)
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(f"{TYPES}/{t.uuid}").status_code, 404)

    def test_pay_percent_range(self):
        self.authenticate_as(self.hr)
        res = self.client.post(TYPES, {**TYPE_BODY, "pay_percent": 101}, format="json")
        self.assertEqual((res.status_code, res.data["type"]), (400, "validation"))

    def test_duplicate_name_and_bad_allowance(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.post(TYPES, {**TYPE_BODY, "name": "Annual"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(TYPES, {**TYPE_BODY, "yearly_allowance": -1}, format="json").status_code, 400)

    def test_delete_used_type_400(self):
        make_request(self.agent, K.LEAVE, D(2026, 11, 2), leave_type=self.annual)
        self.authenticate_as(self.hr)
        res = self.client.delete(f"{TYPES}/{self.annual.uuid}")
        self.assertEqual((res.status_code, res.data["type"]), (400, "in_use"))
        self.assertTrue(LeaveType.objects.filter(pk=self.annual.pk).exists())


class AllowanceTests(LeaveApiBase):
    def body(self, **kw):
        return {"user": str(self.agent.uuid), "leave_type": str(self.annual.uuid), "year": 2026, "days": 25, **kw}

    def test_agent_forbidden(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(ALLOW).status_code, 403)

    def test_allowance_crud_and_duplicate(self):
        self.authenticate_as(self.hr)
        res = self.client.post(ALLOW, self.body(), format="json")
        self.assertEqual((res.status_code, res.data["days"]), (201, 25))
        dup = self.client.post(ALLOW, self.body(days=3), format="json")
        self.assertEqual((dup.status_code, dup.data["type"]), (400, "duplicate"))
        url = f"{ALLOW}/{res.data['uuid']}"
        self.assertEqual(self.client.patch(url, {"days": 12.5}, format="json").data["days"], 12.5)
        self.assertEqual(self.client.patch(url, {"days": -1}, format="json").status_code, 400)
        self.client.post(ALLOW, self.body(user=str(self.outsider.uuid)), format="json")
        self.assertEqual(len(self.client.get(ALLOW).data), 2)
        self.assertEqual(len(self.client.get(ALLOW, {"user": str(self.agent.uuid), "year": 2026}).data), 1)
        self.assertEqual(len(self.client.get(ALLOW, {"year": 2025}).data), 0)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(LeaveAllowance.objects.filter(user=self.agent).exists())

    def test_bad_references(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.post(ALLOW, self.body(user="nope"), format="json").status_code, 400)
        self.assertEqual(self.client.post(ALLOW, self.body(year="x"), format="json").status_code, 400)


class BalanceTests(LeaveApiBase):
    def test_balances_scope(self):
        self.authenticate_as(self.agent)
        res = self.client.get(BAL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["year"], 2026)
        row = res.data["results"][0]
        self.assertEqual((row["leave_type"]["name"], row["allowance"], row["remaining"]), ("Annual", 21, 21))
        self.assertIsInstance(row["leave_type"]["uuid"], str)
        self.assertEqual(self.client.get(BAL, {"user": str(self.outsider.uuid)}).status_code, 403)
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(BAL, {"user": str(self.agent.uuid)}).status_code, 200)
        self.assertEqual(self.client.get(BAL, {"user": str(self.outsider.uuid)}).status_code, 403)
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get(BAL, {"user": str(self.outsider.uuid), "year": 2025}).data["year"], 2025)

    def test_bad_params(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get(BAL, {"user": "nope"}).status_code, 400)
        self.assertEqual(self.client.get(BAL, {"user": str(dt.date.today())}).status_code, 400)
        self.assertEqual(self.client.get(BAL, {"year": "abc"}).status_code, 400)


class WorkingDaysTests(LeaveApiBase):
    def test_working_days_endpoint(self):
        self.authenticate_as(self.agent)
        res = self.client.get(WD, {"start": "2026-10-22", "end": "2026-10-25"})  # Thu-Sun, Fri/Sat weekend
        self.assertEqual((res.status_code, res.data), (200, {"days": 2}))
        bad = self.client.get(WD, {"start": "2026-10-25", "end": "2026-10-22"})
        self.assertEqual((bad.status_code, bad.data["type"]), (400, "validation"))
        self.assertEqual(self.client.get(WD, {"start": "x", "end": "2026-10-22"}).status_code, 400)
        self.assertEqual(self.client.get(WD, {"start": "2026-10-22"}).status_code, 400)

    def test_scope(self):
        self.authenticate_as(self.agent)
        res = self.client.get(WD, {"user": str(self.outsider.uuid), "start": "2026-10-22", "end": "2026-10-25"})
        self.assertEqual(res.status_code, 403)
        self.authenticate_as(self.hr)
        res = self.client.get(WD, {"user": str(self.outsider.uuid), "start": "2026-10-22", "end": "2026-10-25"})
        self.assertEqual(res.status_code, 200)
