import uuid
from datetime import date, datetime as dt, timedelta
from unittest import mock

from apps.attendance.models import (AttendanceSettings, DeductionPolicy, DeductionTier, Holiday,
                                    ShiftAssignment, WebPunchPolicy)
from apps.attendance.tests.factories import assign, make_policy, make_shift
from apps.users.models import Department, User, ZKConfig
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

B = "/api/attendance/"
NOW = dt(2026, 10, 21, 12, 0, 0)


class ConfigBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("apps.attendance.views.config._now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = User.objects.create_user(
            username="mgr", password="x", role=UserTypes.MANAGER, department=self.department)
        self.authenticate_as(self.superuser)


class ShiftTests(ConfigBase):
    def body(self, **kw):
        d = {"name": "Morning", "start_time": "09:00", "end_time": "17:00", "weekend_days": [4, 5],
             "grace_minutes": 10}
        d.update(kw)
        return d

    def test_create_and_patch(self):
        r = self.client.post(B + "shifts", self.body(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["start_time"], "09:00")
        self.assertFalse(r.data["crosses_midnight"])
        self.assertTrue(r.data["active"])
        r2 = self.client.patch(f"{B}shifts/{r.data['uuid']}", {"grace_minutes": 20, "end_time": "05:00"},
                               format="json")
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertEqual(r2.data["grace_minutes"], 20)
        self.assertTrue(r2.data["crosses_midnight"])
        self.assertEqual(r2.data["name"], "Morning")

    def test_delete_not_allowed(self):
        s = make_shift()
        self.assertEqual(self.client.delete(f"{B}shifts/{s.uuid}").status_code, 405)

    def test_validation(self):
        make_shift(name="Dup")
        for kw in ({"name": "Dup"}, {"weekend_days": [7]}, {"weekend_days": [1, 1]},
                   {"weekend_days": "x"}, {"grace_minutes": 121}, {"grace_minutes": -1},
                   {"start_time": "9am"}, {"start_time": None}, {"name": ""}):
            r = self.client.post(B + "shifts", self.body(**kw), format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "validation"), (kw, r.data))
        r = self.client.post(B + "shifts", {"name": "X"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_bad_bodies_are_400(self):
        for body in ([1], "x", 5):
            r = self.client.post(B + "shifts", body, format="json")
            self.assertEqual(r.status_code, 400, body)
            r = self.client.post(B + "shift-assignments", body, format="json")
            self.assertEqual(r.status_code, 400, body)
        for kw in ({"grace_minutes": "abc"}, {"weekend_days": "x"}, {"name": 5}, {"active": "y"}):
            r = self.client.post(B + "shifts", self.body(**kw), format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "validation"), kw)
        s = make_shift()
        for kw in ({"shift": 5}, {"shift": ["a"]}, {"department": 5}, {"effective_from": 20261101},
                   {"department": {"a": 1}}):
            body = {"shift": str(s.uuid), "department": str(self.department.uuid),
                    "effective_from": "2026-11-01"}
            body.update(kw)
            r = self.client.post(B + "shift-assignments", body, format="json")
            self.assertEqual(r.status_code, 400, kw)

    def test_unknown_uuid(self):
        r = self.client.patch(f"{B}shifts/{uuid.uuid4()}", {}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (404, "not_found"))

    def test_permissions(self):
        s = make_shift()
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(B + "shifts").status_code, 200)
        self.assertEqual(self.client.post(B + "shifts", self.body(), format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{B}shifts/{s.uuid}", {}, format="json").status_code, 403)
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(B + "shifts").status_code, 403)


class AssignmentTests(ConfigBase):
    def test_create_department_and_user(self):
        s = make_shift()
        r = self.client.post(B + "shift-assignments", {
            "shift": str(s.uuid), "department": str(self.department.uuid),
            "effective_from": "2026-11-01"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["shift_name"], s.name)
        self.assertEqual(r.data["department_name"], self.department.name)
        self.assertIsNone(r.data["user"])
        r = self.client.post(B + "shift-assignments", {
            "shift": str(s.uuid), "user": str(self.agent.uuid), "effective_from": "2026-11-01"},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["username"], "agent")

    def test_validation(self):
        s = make_shift()
        base = {"shift": str(s.uuid), "effective_from": "2026-11-01"}
        both = dict(base, department=str(self.department.uuid), user=str(self.agent.uuid))
        for body in (base, both, dict(base, user=str(uuid.uuid4())),
                     dict(base, department=str(uuid.uuid4())),
                     {"department": str(self.department.uuid), "effective_from": "2026-11-01"},
                     dict(base, shift=str(uuid.uuid4()), department=str(self.department.uuid)),
                     dict(base, department=str(self.department.uuid), effective_from="bad")):
            r = self.client.post(B + "shift-assignments", body, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "validation"), (body, r.data))

    def test_duplicate_date_is_400(self):
        s = make_shift()
        assign(s, department=self.department, effective_from=date(2026, 11, 1))
        r = self.client.post(B + "shift-assignments", {
            "shift": str(s.uuid), "department": str(self.department.uuid),
            "effective_from": "2026-11-01"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "validation"))

    def test_list_filters_and_order(self):
        s = make_shift()
        other = Department.objects.create(name="Other")
        a1 = assign(s, department=self.department, effective_from=date(2026, 9, 1))
        a2 = assign(s, department=self.department, effective_from=date(2026, 10, 1))
        assign(s, department=other)
        assign(s, user=self.agent)
        r = self.client.get(B + "shift-assignments", {"department": str(self.department.uuid)})
        self.assertEqual([x["uuid"] for x in r.data], [str(a2.uuid), str(a1.uuid)])
        r = self.client.get(B + "shift-assignments", {"user": str(self.agent.uuid)})
        self.assertEqual(len(r.data), 1)
        self.assertEqual(len(self.client.get(B + "shift-assignments").data), 4)
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(B + "shift-assignments").status_code, 200)

    def test_delete_rules(self):
        s = make_shift()
        past = assign(s, department=self.department, effective_from=date(2026, 10, 21))
        future = assign(s, user=self.agent, effective_from=date(2026, 10, 22))
        r = self.client.delete(f"{B}shift-assignments/{past.uuid}")
        self.assertEqual((r.status_code, r.data["type"]), (400, "validation"))
        self.assertEqual(self.client.delete(f"{B}shift-assignments/{future.uuid}").status_code, 204)
        self.assertFalse(ShiftAssignment.objects.filter(pk=future.pk).exists())
        self.assertEqual(self.client.delete(f"{B}shift-assignments/{uuid.uuid4()}").status_code, 404)

    def test_manager_cannot_write(self):
        s = make_shift()
        self.authenticate_as(self.manager)
        r = self.client.post(B + "shift-assignments", {
            "shift": str(s.uuid), "department": str(self.department.uuid),
            "effective_from": "2026-11-01"}, format="json")
        self.assertEqual(r.status_code, 403)


class HolidayTests(ConfigBase):
    def test_create_list_delete(self):
        r = self.client.post(B + "holidays", {"date": "2026-10-06", "name": "Armed Forces"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(r.data["department"])
        r2 = self.client.post(B + "holidays", {"date": "2027-01-07", "name": "Xmas",
                                               "department": str(self.department.uuid)}, format="json")
        self.assertEqual(r2.data["department_name"], self.department.name)
        self.authenticate_as(self.agent)
        r = self.client.get(B + "holidays")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([h["date"] for h in r.data], ["2026-10-06", "2027-01-07"])
        self.assertEqual([h["date"] for h in self.client.get(B + "holidays", {"year": 2027}).data],
                         ["2027-01-07"])
        self.assertEqual(self.client.get(B + "holidays", {"year": "x"}).status_code, 400)
        self.assertEqual(self.client.delete(f"{B}holidays/{r2.data['uuid']}").status_code, 403)
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.delete(f"{B}holidays/{r2.data['uuid']}").status_code, 204)
        self.assertEqual(self.client.delete(f"{B}holidays/{r2.data['uuid']}").status_code, 404)

    def test_validation(self):
        Holiday.objects.create(date=date(2026, 10, 6), name="A")
        for body in ({"date": "2026-10-06", "name": "dup"}, {"date": "bad", "name": "x"},
                     {"date": "2026-10-07", "name": ""}, {"date": "2026-10-07"},
                     {"date": "2026-10-07", "name": "x", "department": str(uuid.uuid4())}):
            r = self.client.post(B + "holidays", body, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "validation"), (body, r.data))

    def test_agent_cannot_create(self):
        self.authenticate_as(self.agent)
        r = self.client.post(B + "holidays", {"date": "2026-10-07", "name": "x"}, format="json")
        self.assertEqual(r.status_code, 403)


class PolicyTests(ConfigBase):
    def test_list_includes_global(self):
        make_policy(None, allowance=3, late=[(15, 0.25)])
        r = self.client.get(B + "policies")
        self.assertEqual(r.status_code, 200)
        g = [p for p in r.data if p["department"] is None][0]
        self.assertEqual(g["monthly_late_allowance"], 3)
        self.assertEqual(g["tiers"], [{"kind": "LATE", "min_minutes": 15, "deduction_days": 0.25}])
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(B + "policies").status_code, 403)

    def test_create(self):
        r = self.client.post(B + "policies", {"department": str(self.department.uuid),
                                              "monthly_late_allowance": 2}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["department_name"], self.department.name)
        self.assertEqual(r.data["tiers"], [])
        r = self.client.post(B + "policies", {"department": str(self.department.uuid)}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate"))
        for body in ({}, {"department": None}, {"department": str(uuid.uuid4())}):
            r = self.client.post(B + "policies", body, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "validation"), body)

    def test_put_replaces_tiers(self):
        p = make_policy(self.department, allowance=1, late=[(15, 0.25), (60, 0.5)], early=[(30, 0.25)])
        r = self.client.put(f"{B}policies/{p.uuid}", {
            "monthly_late_allowance": 5, "absence_days": 0.5,
            "tiers": [{"kind": "LATE", "min_minutes": 10, "deduction_days": 0.1},
                      {"kind": "EARLY_LEAVE", "min_minutes": 10, "deduction_days": 1}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["monthly_late_allowance"], 5)
        self.assertEqual(r.data["absence_days"], 0.5)
        self.assertEqual(sorted((t["kind"], t["min_minutes"]) for t in r.data["tiers"]),
                         [("EARLY_LEAVE", 10), ("LATE", 10)])
        self.assertEqual(DeductionTier.objects.filter(policy=p).count(), 2)

    def test_put_without_tiers_keeps_them(self):
        p = make_policy(self.department, late=[(15, 0.25)])
        r = self.client.put(f"{B}policies/{p.uuid}", {"monthly_late_allowance": 7}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["tiers"]), 1)

    def test_put_invalid_tiers_leaves_data(self):
        p = make_policy(self.department, late=[(15, 0.25)])
        t = lambda k="LATE", m=10, d=0.5: {"kind": k, "min_minutes": m, "deduction_days": d}
        for tiers in ([t(), t()], [t(m=0)], [t(d=1.5)], [t(d=-0.1)], [t(k="BAD")], [t(m="x")],
                      "nope", [5]):
            r = self.client.put(f"{B}policies/{p.uuid}", {"tiers": tiers}, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_tiers"), (tiers, r.data))
        self.assertEqual(list(p.tiers.values_list("min_minutes", flat=True)), [15])

    def test_limits(self):
        p = make_policy(self.department)
        t = lambda m=10, d=0.5: [{"kind": "LATE", "min_minutes": m, "deduction_days": d}]
        for body in ({"monthly_late_allowance": 32}, {"monthly_late_allowance": 10 ** 12},
                     {"absence_days": 1.5}):
            r = self.client.put(f"{B}policies/{p.uuid}", body, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "validation"), body)
        for raw in ('{"absence_days": NaN}', '{"absence_days": Infinity}'):
            r = self.client.generic("PUT", f"{B}policies/{p.uuid}", raw, content_type="application/json")
            self.assertEqual(r.status_code, 400, raw)  # DRF's JSON parser already rejects NaN/Infinity
        r = self.client.post(B + "policies", {"department": str(self.department.uuid),
                                              "monthly_late_allowance": 32}, format="json")
        self.assertEqual(r.status_code, 400)
        for tiers in (t(m=1441), t(m=10 ** 12)):
            r = self.client.put(f"{B}policies/{p.uuid}", {"tiers": tiers}, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_tiers"), tiers)
        for d in ("NaN", "Infinity"):
            raw = '{"tiers": [{"kind": "LATE", "min_minutes": 10, "deduction_days": %s}]}' % d
            r = self.client.generic("PUT", f"{B}policies/{p.uuid}", raw, content_type="application/json")
            self.assertEqual(r.status_code, 400, d)
        for ok in ({"monthly_late_allowance": 31, "absence_days": 1}, {"tiers": t(m=1440, d=1)}):
            self.assertEqual(self.client.put(f"{B}policies/{p.uuid}", ok, format="json").status_code, 200)

    def test_put_validation_and_404(self):
        p = make_policy(self.department)
        r = self.client.put(f"{B}policies/{p.uuid}", {"monthly_late_allowance": -1}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "validation"))
        r = self.client.put(f"{B}policies/{uuid.uuid4()}", {}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (404, "not_found"))

    def test_global_policy_editable(self):
        g = make_policy(None)
        r = self.client.put(f"{B}policies/{g.uuid}", {"monthly_late_allowance": 4}, format="json")
        self.assertEqual(r.status_code, 200)
        g.refresh_from_db()
        self.assertTrue(g.is_global)
        self.assertEqual(g.monthly_late_allowance, 4)


class WebPunchPolicyTests(ConfigBase):
    def test_list_defaults_and_upsert(self):
        r = self.client.get(B + "web-punch-policies")
        row = [x for x in r.data if x["department"] == str(self.department.uuid)][0]
        self.assertEqual((row["require_trusted_device"], row["require_office_ip"], row["allowed_ips"]),
                         (False, False, []))
        self.assertEqual(row["department_name"], self.department.name)
        url = f"{B}web-punch-policies/{self.department.uuid}"
        r = self.client.put(url, {"require_trusted_device": True, "require_office_ip": True,
                                  "allowed_ips": ["10.0.0.0/24", "1.2.3.4", "::1"]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.client.put(url, {"require_trusted_device": False, "require_office_ip": True,
                                  "allowed_ips": ["10.0.0.5"]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(WebPunchPolicy.objects.filter(department=self.department).count(), 1)
        p = WebPunchPolicy.objects.get(department=self.department)
        self.assertEqual((p.require_trusted_device, p.allowed_ips), (False, ["10.0.0.5"]))
        listed = [x for x in self.client.get(B + "web-punch-policies").data
                  if x["department"] == str(self.department.uuid)][0]
        self.assertEqual(listed["allowed_ips"], ["10.0.0.5"])

    def test_invalid(self):
        url = f"{B}web-punch-policies/{self.department.uuid}"
        for ips in (["nope"], ["1.2.3.4/99"], "1.2.3.4", [5]):
            r = self.client.put(url, {"allowed_ips": ips}, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_ips"), ips)
        r = self.client.put(f"{B}web-punch-policies/{uuid.uuid4()}", {}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_department"))
        r = self.client.put(url, {"require_office_ip": "yes"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "validation"))
        self.assertFalse(WebPunchPolicy.objects.exists())

    def test_hr_only(self):
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(B + "web-punch-policies").status_code, 403)
        r = self.client.put(f"{B}web-punch-policies/{self.department.uuid}", {}, format="json")
        self.assertEqual(r.status_code, 403)


class SettingsTests(ConfigBase):
    def test_get_put(self):
        r = self.client.get(B + "settings")
        self.assertEqual(r.data, {"period_start_day": 26, "device_sync_minutes": 60,
                                  "last_nightly_run": None})
        r = self.client.put(B + "settings", {"period_start_day": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["period_start_day"], r.data["device_sync_minutes"]), (1, 60))
        r = self.client.put(B + "settings", {"device_sync_minutes": 5, "last_nightly_run": "2026-01-01"},
                            format="json")
        s = AttendanceSettings.get()
        self.assertEqual(s.device_sync_minutes, 5)
        self.assertIsNone(s.last_nightly_run)

    def test_invalid(self):
        for body in ({"period_start_day": 29}, {"period_start_day": 0}, {"device_sync_minutes": 4},
                     {"device_sync_minutes": 1441}, {"period_start_day": "x"}, {"period_start_day": True}):
            r = self.client.put(B + "settings", body, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "validation"), body)

    def test_hr_only(self):
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(B + "settings").status_code, 403)
        self.assertEqual(self.client.put(B + "settings", {}, format="json").status_code, 403)


class DeviceTests(ConfigBase):
    def test_list(self):
        z = ZKConfig.objects.create(ip="10.0.0.9", port=4370, timeout=5, password="", force_udp=False,
                                    ommit_ping=False, is_default=False, last_uid=0, name="Door",
                                    last_synced_at=dt(2026, 10, 20, 8, 30))
        ZKConfig.objects.create(ip="10.0.0.10", port=4370, timeout=5, password="", force_udp=False,
                                ommit_ping=False, is_default=False, last_uid=0)
        r = self.client.get(B + "devices")
        self.assertEqual(r.status_code, 200)
        row = [d for d in r.data if d["uuid"] == str(z.uuid)][0]
        self.assertEqual(row, {"uuid": str(z.uuid), "name": "Door", "ip": "10.0.0.9", "port": 4370,
                               "last_synced_at": "2026-10-20T08:30:00"})
        self.assertTrue(any(d["last_synced_at"] is None for d in r.data))
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(B + "devices").status_code, 403)
