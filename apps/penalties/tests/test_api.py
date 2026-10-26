from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.penalties.models import Penalty, PenaltyType
from apps.penalties.tests.factories import make_penalty, make_type, make_user
from apps.users.models import Department
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

BASE = "/api/penalties"
TYPES, LIST = f"{BASE}/types", f"{BASE}/penalties"
PENALTY_KEYS = {"uuid", "user", "penalty_type", "title", "description", "date", "kind", "value", "created_by",
                "created_at", "voided_at", "voided_by", "void_reason", "can"}


class PenaltyApiBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = make_user("hr", UserTypes.HR, self.department)
        self.manager = make_user("mgr", UserTypes.MANAGER, self.department)
        self.other_dept = Department.objects.create(name="Other")
        self.outsider = make_user("outsider", UserTypes.AGENT, self.other_dept)
        self.today = timezone.now().date().isoformat()

    def body(self, **kw):
        base = {"user": str(self.agent.uuid), "title": "Late", "kind": "days", "value": "0.5", "date": self.today}
        base.update(kw)
        return base

    def post(self, user, data):
        self.authenticate_as(user)
        return self.client.post(LIST, data, format="json")


class TypeTests(PenaltyApiBase):
    def test_types_list_any_user(self):
        make_type(name="B")
        make_type(name="A")
        self.authenticate_as(self.agent)
        r = self.client.get(TYPES)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["name"] for t in r.data], ["A", "B"])
        self.assertEqual(set(r.data[0]), {"uuid", "name", "kind", "default_value", "is_active"})

    def test_types_active_filter(self):
        make_type(name="A")
        make_type(name="B", is_active=False)
        self.authenticate_as(self.agent)
        self.assertEqual(len(self.client.get(TYPES, {"active": 1}).data), 1)
        self.assertEqual(len(self.client.get(TYPES).data), 2)

    def test_types_create_hr_only(self):
        data = {"name": "Late", "kind": "days", "default_value": "0.5"}
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.post(TYPES, data, format="json").status_code, 403)
        self.authenticate_as(self.hr)
        r = self.client.post(TYPES, data, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["default_value"], "0.50")

    def test_types_create_validation(self):
        make_type(name="Late")
        self.authenticate_as(self.hr)
        for bad in ({"name": "Late", "kind": "days", "default_value": "1"},
                    {"name": " ", "kind": "days", "default_value": "1"},
                    {"name": "X", "kind": "nope", "default_value": "1"},
                    {"name": "X", "kind": "days", "default_value": "0"},
                    {"name": "X", "kind": "days", "default_value": "abc"},
                    {"name": "X", "kind": "days", "default_value": "1e30"},
                    {"name": "X", "kind": "days", "default_value": "NaN"}):
            r = self.client.post(TYPES, bad, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), bad)

    def test_types_default_must_fit_kind(self):
        self.authenticate_as(self.hr)
        for bad in ("0.25", "0.001"):
            r = self.client.post(TYPES, {"name": "X", "kind": "days", "default_value": bad}, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), bad)
        r = self.client.post(TYPES, {"name": "X", "kind": "days", "default_value": "0.5"}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_types_patch_validates_merged_kind_and_default(self):
        self.authenticate_as(self.hr)
        t = make_type(name="M", kind="money", default_value=Decimal("12.34"))
        r = self.client.patch(f"{TYPES}/{t.uuid}", {"kind": "days"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        t2 = make_type(name="M2", kind="money", default_value=Decimal("2.00"))
        r = self.client.patch(f"{TYPES}/{t2.uuid}", {"kind": "days"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_types_patch_hr(self):
        t = make_type()
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.patch(f"{TYPES}/{t.uuid}", {"is_active": False}, format="json").status_code, 403)
        self.authenticate_as(self.hr)
        r = self.client.patch(f"{TYPES}/{t.uuid}", {"is_active": False, "default_value": "2"}, format="json")
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual((t.is_active, t.default_value), (False, Decimal("2.00")))
        make_type(name="Other")
        r = self.client.patch(f"{TYPES}/{t.uuid}", {"name": "Other"}, format="json")
        self.assertEqual(r.status_code, 400)


class CreateTests(PenaltyApiBase):
    def test_create_201_and_shape(self):
        r = self.post(self.hr, self.body())
        self.assertEqual(r.status_code, 201)
        self.assertEqual(set(r.data), PENALTY_KEYS)
        self.assertTrue(r.data["can"]["void"])
        self.assertEqual(r.data["value"], "0.50")
        self.assertEqual(r.data["user"], {"uuid": str(self.agent.uuid), "name": "agent", "username": "agent"})
        self.assertIsNone(r.data["penalty_type"])

    def test_create_with_type(self):
        t = make_type(name="Absent", kind="money", default_value=Decimal("50"))
        r = self.post(self.hr, {"user": str(self.agent.uuid), "penalty_type": str(t.uuid), "date": self.today})
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.data["title"], r.data["kind"], r.data["value"]), ("Absent", "money", "50.00"))
        self.assertEqual(r.data["penalty_type"], {"uuid": str(t.uuid), "name": "Absent"})

    def test_create_forbidden_403(self):
        r = self.post(self.agent, self.body(user=str(self.hr.uuid)))
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        r = self.post(self.manager, self.body(user=str(self.outsider.uuid)))
        self.assertEqual(r.status_code, 403)

    def test_create_self_penalty_400(self):
        r = self.post(self.manager, self.body(user=str(self.manager.uuid)))
        self.assertEqual((r.status_code, r.data["type"]), (400, "self_penalty"))

    def test_create_value_garbage_400(self):
        for v in ("abc", "NaN", "Infinity", "1e30", "100000000"):
            r = self.post(self.hr, self.body(value=v))
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), v)
        self.assertEqual(Penalty.objects.count(), 0)

    def test_create_unknown_user_400(self):
        r = self.post(self.hr, self.body(user="00000000-0000-0000-0000-000000000000"))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.post(self.hr, self.body(user="nope"))
        self.assertEqual(r.status_code, 400)

    def test_create_unknown_type_400(self):
        r = self.post(self.hr, self.body(penalty_type="00000000-0000-0000-0000-000000000000"))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_create_bad_date_400(self):
        for d in ("2026-13-45", None):
            r = self.post(self.hr, self.body(date=d))
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_create_service_error_mapped(self):
        r = self.post(self.hr, self.body(date="2999-01-01"))
        self.assertEqual((r.status_code, r.data["type"]), (400, "future_date"))


class ListTests(PenaltyApiBase):
    def setUp(self):
        super().setUp()
        self.p_agent = make_penalty(self.agent, self.hr, title="Late arrival", description="bus")
        self.p_out = make_penalty(self.outsider, self.hr, title="Damage", kind="money", value=Decimal("10"),
                                  date=date(2026, 9, 1))
        self.p_mgr = make_penalty(self.manager, self.hr, title="Own")

    def uuids(self, viewer, **params):
        self.authenticate_as(viewer)
        r = self.client.get(LIST, params)
        self.assertEqual(r.status_code, 200, r.data)
        return {x["uuid"] for x in r.data["results"]}

    def test_list_scoped_per_role(self):
        self.assertEqual(self.uuids(self.hr), {str(p.uuid) for p in (self.p_agent, self.p_out, self.p_mgr)})
        self.assertEqual(self.uuids(self.manager), {str(self.p_agent.uuid), str(self.p_mgr.uuid)})
        self.assertEqual(self.uuids(self.agent), {str(self.p_agent.uuid)})

    def test_list_scope_mine(self):
        self.assertEqual(self.uuids(self.hr, scope="mine"), set())
        self.assertEqual(self.uuids(self.manager, scope="mine"), {str(self.p_mgr.uuid)})

    def test_list_filters_status_kind_type_custom_dates_search(self):
        t = make_type()
        typed = make_penalty(self.agent, self.hr, title="Typed", penalty_type=t)
        voided = make_penalty(self.agent, self.hr, title="Gone", voided_at=timezone.now(), voided_by=self.hr)
        u = lambda *ps: {str(p.uuid) for p in ps}
        self.assertIn(str(voided.uuid), self.uuids(self.hr, status="voided"))
        self.assertEqual(self.uuids(self.hr, status="voided"), u(voided))
        self.assertNotIn(str(voided.uuid), self.uuids(self.hr, status="active"))
        self.assertEqual(self.uuids(self.hr, kind="money"), u(self.p_out))
        self.assertEqual(self.uuids(self.hr, type=str(t.uuid)), u(typed))
        self.assertNotIn(str(typed.uuid), self.uuids(self.hr, type="custom"))
        self.assertIn(str(self.p_out.uuid), self.uuids(self.hr, type="custom"))
        self.assertEqual(self.uuids(self.hr, to="2026-09-01"), u(self.p_out))
        self.assertEqual(self.uuids(self.hr, **{"from": "2026-09-02"}) & u(self.p_out), set())
        self.assertEqual(self.uuids(self.hr, **{"from": "2026-09-01", "to": "2026-09-01"}), u(self.p_out))
        self.assertEqual(self.uuids(self.hr, search="bus"), u(self.p_agent))
        self.assertEqual(self.uuids(self.hr, search="DAMAGE"), u(self.p_out))
        self.assertEqual(self.uuids(self.hr, search="outsid"), u(self.p_out))
        self.assertEqual(self.uuids(self.hr, user=str(self.outsider.uuid)), u(self.p_out))
        self.assertEqual(self.uuids(self.hr, user="garbage"), set())

    def test_list_bad_date_400(self):
        self.authenticate_as(self.hr)
        r = self.client.get(LIST, {"from": "x"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_list_paginated(self):
        self.authenticate_as(self.hr)
        r = self.client.get(LIST)
        self.assertIn("results", r.data)
        self.assertEqual(r.data["count"], 3)
        self.assertEqual(set(r.data["results"][0]), PENALTY_KEYS)


class VoidTests(PenaltyApiBase):
    def url(self, p):
        return f"{LIST}/{p.uuid}/void"

    def test_void_200(self):
        p = make_penalty(self.agent, self.hr)
        self.authenticate_as(self.hr)
        r = self.client.post(self.url(p), {"reason": " oops "}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["void_reason"], "oops")
        self.assertIsNotNone(r.data["voided_at"])
        self.assertFalse(r.data["can"]["void"])
        self.assertEqual(r.data["voided_by"]["uuid"], str(self.hr.uuid))

    def test_void_invisible_404(self):
        p = make_penalty(self.outsider, self.hr)
        self.authenticate_as(self.agent)
        r = self.client.post(self.url(p), {"reason": "x"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (404, "not_found"))

    def test_void_visible_but_forbidden_403(self):
        p = make_penalty(self.agent, self.hr)
        self.authenticate_as(self.manager)
        r = self.client.post(self.url(p), {"reason": "x"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))

    def test_void_blank_reason_400(self):
        p = make_penalty(self.agent, self.hr)
        self.authenticate_as(self.hr)
        for body in ({"reason": "  "}, {}, {"reason": 5}):
            r = self.client.post(self.url(p), body, format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_void_twice_400(self):
        p = make_penalty(self.agent, self.hr)
        self.authenticate_as(self.hr)
        self.client.post(self.url(p), {"reason": "a"}, format="json")
        r = self.client.post(self.url(p), {"reason": "a"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "already_voided"))


class PeriodTotalTests(PenaltyApiBase):
    def get(self, viewer, **params):
        self.authenticate_as(viewer)
        return self.client.get(f"{LIST}/period-total", params)

    def test_period_total_ok(self):
        make_penalty(self.agent, self.hr, date=date(2026, 10, 5), value=Decimal("1.5"))
        r = self.get(self.agent, user=str(self.agent.uuid), period="2026-10")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["days"], r.data["count"], r.data["period"]), ("1.50", 1, "2026-10"))
        self.assertEqual(self.get(self.manager, user=str(self.agent.uuid), period="2026-10").status_code, 200)

    def test_period_total_bad_key_400(self):
        r = self.get(self.hr, user=str(self.agent.uuid), period="2026-13")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        self.assertEqual(self.get(self.hr, user=str(self.agent.uuid)).status_code, 400)

    def test_period_total_bad_user_400(self):
        self.assertEqual(self.get(self.hr, period="2026-10").status_code, 400)
        self.assertEqual(self.get(self.hr, user="zzz", period="2026-10").status_code, 400)
        r = self.get(self.hr, user="00000000-0000-0000-0000-000000000000", period="2026-10")
        self.assertEqual(r.status_code, 400)

    def test_period_total_forbidden_403(self):
        r = self.get(self.agent, user=str(self.hr.uuid), period="2026-10")
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))


class MetaTargetsTests(PenaltyApiBase):
    def meta(self, user):
        self.authenticate_as(user)
        r = self.client.get(f"{LIST}/meta")
        self.assertEqual(r.status_code, 200)
        return r.data

    def targets(self, user, **params):
        self.authenticate_as(user)
        r = self.client.get(f"{LIST}/targets", params)
        self.assertEqual(r.status_code, 200)
        return r.data

    def test_meta_per_role(self):
        self.assertEqual(self.meta(self.hr), {"can_add": True, "can_manage_types": True})
        self.assertEqual(self.meta(self.manager), {"can_add": True, "can_manage_types": False})
        self.assertEqual(self.meta(self.agent), {"can_add": False, "can_manage_types": False})

    def test_targets_per_role_and_search(self):
        names = lambda data: {t["username"] for t in data}
        self.assertEqual(names(self.targets(self.manager)), {"superuser", "agent", "hr"})
        hr_names = names(self.targets(self.hr))
        self.assertNotIn("hr", hr_names)
        self.assertEqual(hr_names, {"superuser", "agent", "mgr", "outsider"})
        self.assertEqual(self.targets(self.agent), [])
        found = self.targets(self.hr, search="OUTS")
        self.assertEqual(found, [{"uuid": str(self.outsider.uuid), "name": "outsider", "username": "outsider"}])

    def test_targets_excludes_inactive_and_orders_by_name(self):
        zed = make_user("zed", UserTypes.AGENT)
        zed.is_active = False
        zed.save()
        self.agent.first_name = "Zoe"
        self.agent.save()
        self.outsider.first_name = "Amy"
        self.outsider.save()
        data = self.targets(self.hr)
        self.assertNotIn("zed", {t["username"] for t in data})
        order = [t["username"] for t in data]
        self.assertLess(order.index("outsider"), order.index("agent"))
        self.assertEqual(data[order.index("outsider")]["name"], "Amy")

    def test_manager_without_department_meta_and_targets(self):
        loner = make_user("loner", UserTypes.MANAGER, None)
        self.assertEqual(self.meta(loner), {"can_add": False, "can_manage_types": False})
        self.assertEqual(self.targets(loner), [])
