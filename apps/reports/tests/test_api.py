from datetime import datetime
from datetime import date, timedelta

from apps.reports.models import ReportSubmission
from apps.reports.tests.base import ReportsTestCase
from apps.teams.models import Team
from apps.users.models import User
from apps.users.types import UserTypes

BASE = "/api/reports"


class ReportsApiBase(ReportsTestCase):
    def setUp(self):
        super().setUp()
        mk = lambda name, role, dept=None: User.objects.create_user(
            username=name, password="pass123", email=f"{name}@t.com", role=role, department=dept)
        self.mk = mk
        self.mkt_agent = mk("mkt", UserTypes.AGENT, self.marketing)
        self.hr = mk("hr", UserTypes.HR)
        self.manager = mk("mgr", UserTypes.MANAGER, self.department)
        User.objects.all().update(date_joined=datetime(2020, 1, 1))
        self.today = date.today()
        self.rt = self.make_type(name="Daily")
        self.field = self.rt.sections.first().fields.get(label="n")

    def get(self, user, path):
        self.authenticate_as(user)
        return self.client.get(f"{BASE}/{path}")

    def send(self, method, user, path, data=None):
        self.authenticate_as(user)
        return getattr(self.client, method)(f"{BASE}/{path}", data, format="json")


class AccessTests(ReportsApiBase):
    def test_flags(self):
        r = self.get(self.mkt_agent, "access")
        self.assertEqual(r.data, {"fill": True, "view_board": False, "manage": False, "dashboard": False})
        r = self.get(self.agent, "access")
        self.assertEqual(r.data, {"fill": False, "view_board": False, "manage": False, "dashboard": False})
        r = self.get(self.manager, "access")
        self.assertEqual(r.data, {"fill": False, "view_board": True, "manage": False, "dashboard": True})
        r = self.get(self.hr, "access")
        self.assertEqual(r.data, {"fill": False, "view_board": True, "manage": True, "dashboard": True})

    def test_leader_can_view_board(self):
        Team.objects.create(name="T", department=self.marketing, leader=self.mkt_agent)
        self.assertTrue(self.get(self.mkt_agent, "access").data["view_board"])


class MyTests(ReportsApiBase):
    def test_only_assigned_active(self):
        self.make_type(name="Other", departments=[self.department])
        self.make_type(name="Off", is_active=False)
        r = self.get(self.mkt_agent, "my")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["name"] for t in r.data], ["Daily"])
        t = r.data[0]
        self.assertEqual(len(t["periods"]), 7)
        p = t["periods"][0]
        self.assertEqual(set(p), {"start", "end", "status", "can_edit", "reason", "submission"})
        self.assertEqual(p["start"], self.today.isoformat())
        self.assertEqual(p["status"], "missing")
        self.assertTrue(p["can_edit"])
        self.assertIsNone(p["submission"])
        self.assertTrue(t["sections"])

    def test_window_limits_edit(self):
        self.rt.edit_window_days = 1
        self.rt.save()
        r = self.get(self.mkt_agent, "my")
        flags = [p["can_edit"] for p in r.data[0]["periods"]]
        self.assertEqual(flags, [True, True] + [False] * 5)
        self.assertEqual(r.data[0]["periods"][2]["reason"], "window_passed")

    def test_submitted_status(self):
        self.send("post", self.mkt_agent, f"types/{self.rt.uuid}/submit",
                  {"date": self.today.isoformat(), "values": {str(self.field.uuid): 5}})
        r = self.get(self.mkt_agent, "my")
        p = r.data[0]["periods"][0]
        self.assertEqual(p["status"], "submitted")
        self.assertIsNotNone(p["submission"])


class SubmitTests(ReportsApiBase):
    def url(self):
        return f"types/{self.rt.uuid}/submit"

    def test_happy_path_and_get(self):
        r = self.send("post", self.mkt_agent, self.url(),
                      {"date": self.today.isoformat(), "values": {str(self.field.uuid): 5}})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["values"][str(self.field.uuid)], "5.00")
        self.assertEqual(ReportSubmission.objects.count(), 1)
        r2 = self.send("post", self.mkt_agent, self.url(),
                       {"date": self.today.isoformat(), "values": {str(self.field.uuid): 7}})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(ReportSubmission.objects.count(), 1)

    def test_validation_fields(self):
        r = self.send("post", self.mkt_agent, self.url(), {"date": self.today.isoformat(), "values": {}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "invalid")
        self.assertIn(str(self.field.uuid), r.data["fields"])

    def test_bad_shapes(self):
        for body in ({"date": self.today.isoformat(), "values": []}, {"date": "nope", "values": {}},
                     {"values": {}}, []):
            r = self.send("post", self.mkt_agent, self.url(), body)
            self.assertEqual(r.status_code, 400, body)

    def test_not_assigned(self):
        r = self.send("post", self.agent, self.url(),
                      {"date": self.today.isoformat(), "values": {str(self.field.uuid): 5}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "not_assigned")

    def test_unknown_type_404(self):
        r = self.send("post", self.mkt_agent, "types/00000000-0000-0000-0000-000000000000/submit",
                      {"date": self.today.isoformat(), "values": {}})
        self.assertEqual(r.status_code, 404)


class BoardTests(ReportsApiBase):
    def test_forbidden_for_agent(self):
        self.assertEqual(self.get(self.mkt_agent, f"types/{self.rt.uuid}/board").status_code, 403)

    def test_manager_ok(self):
        r = self.get(self.hr, f"types/{self.rt.uuid}/board?date={self.today.isoformat()}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["period"]["start"], self.today.isoformat())
        self.assertEqual(r.data["summary"]["missing"], 1)

    def test_bad_date(self):
        self.assertEqual(self.get(self.hr, f"types/{self.rt.uuid}/board?date=zzz").status_code, 400)


class TypeCrudTests(ReportsApiBase):
    def payload(self, **kw):
        d = {"name": "New", "description": "d", "is_active": True, "frequency": "weekly",
             "edit_window_days": 3, "departments": [str(self.marketing.uuid)],
             "excluded_users": [str(self.mkt_agent.uuid)], "remind_agents": True, "remind_at": "18:30",
             "digest_leaders": True, "order": 2,
             "sections": [{"name": "A", "fields": [{"label": "x", "kind": "number", "required": True}]}]}
        d.update(kw)
        return d

    def test_forbidden_for_manager(self):
        self.assertEqual(self.get(self.manager, "types").status_code, 403)
        self.assertEqual(self.send("post", self.manager, "types", self.payload()).status_code, 403)
        self.assertEqual(self.send("put", self.manager, f"types/{self.rt.uuid}", self.payload()).status_code, 403)
        self.assertEqual(self.send("delete", self.manager, f"types/{self.rt.uuid}").status_code, 403)

    def test_create_update_list_delete(self):
        r = self.send("post", self.hr, "types", self.payload())
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data
        self.assertEqual(d["remind_at"], "18:30")
        self.assertEqual(d["departments"], [str(self.marketing.uuid)])
        self.assertEqual(d["excluded_users"][0]["uuid"], str(self.mkt_agent.uuid))
        self.assertEqual(d["sections"][0]["fields"][0]["label"], "x")
        self.assertEqual(d["submissions_count"], 0)
        self.assertEqual(set(d), {"uuid", "name", "description", "is_active", "frequency", "edit_window_days",
                                  "departments", "excluded_users", "remind_agents", "remind_at",
                                  "digest_leaders", "order", "submissions_count", "sections"})
        sec = d["sections"][0]
        body = self.payload(name="Renamed", excluded_users=[], sections=[sec])
        r = self.send("put", self.hr, f"types/{d['uuid']}", body)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["name"], "Renamed")
        self.assertEqual(r.data["excluded_users"], [])
        self.assertEqual(len(self.get(self.hr, "types").data), 2)
        self.assertEqual(self.send("delete", self.hr, f"types/{d['uuid']}").status_code, 204)

    def test_invalid_payloads(self):
        for kw in ({"name": ""}, {"frequency": "yearly"}, {"remind_at": "25:99"},
                   {"departments": ["bad"]}, {"sections": "x"}, {"sections": [{"name": "a"}]},
                   {"sections": [1]}, {"departments": [str(self.marketing.uuid), "00000000-0000-0000-0000-000000000000"]},
                   {"edit_window_days": -1}):
            r = self.send("post", self.hr, "types", self.payload(**kw))
            self.assertEqual(r.status_code, 400, kw)
            self.assertEqual(r.data["type"], "invalid", kw)

    def test_duplicate_uuids_rejected(self):
        sec = {"uuid": str(self.rt.sections.first().uuid), "name": "S", "fields": []}
        r = self.send("put", self.hr, f"types/{self.rt.uuid}", self.payload(sections=[sec, sec]))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "invalid")

    def test_duplicate_name_400(self):
        r = self.send("post", self.hr, "types", self.payload(name="daily"))
        self.assertEqual(r.status_code, 400)

    def test_delete_with_submissions(self):
        self.send("post", self.mkt_agent, f"types/{self.rt.uuid}/submit",
                  {"date": self.today.isoformat(), "values": {str(self.field.uuid): 1}})
        r = self.send("delete", self.hr, f"types/{self.rt.uuid}")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "has_submissions")

    def test_options_only_active(self):
        self.make_type(name="Off", is_active=False)
        r = self.get(self.manager, "types/options")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["name"] for t in r.data], ["Daily"])
        self.assertEqual(set(r.data[0]), {"uuid", "name", "frequency"})
        self.assertEqual(self.get(self.mkt_agent, "types/options").status_code, 403)


class SubmissionDetailTests(ReportsApiBase):
    def setUp(self):
        super().setUp()
        self.send("post", self.mkt_agent, f"types/{self.rt.uuid}/submit",
                  {"date": self.today.isoformat(), "values": {str(self.field.uuid): 5}})
        self.sub = ReportSubmission.objects.get()

    def test_owner_and_supervisor(self):
        r = self.get(self.mkt_agent, f"submissions/{self.sub.uuid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"uuid", "report_type", "user", "period", "is_late", "submitted_at",
                                       "values", "can_edit", "reason"})
        self.assertEqual(r.data["period"], {"start": self.today.isoformat(), "end": self.today.isoformat()})
        self.assertEqual(self.get(self.hr, f"submissions/{self.sub.uuid}").status_code, 200)
        Team.objects.create(name="T", department=self.marketing, leader=self.manager).agents.add(self.mkt_agent)
        self.assertEqual(self.get(self.manager, f"submissions/{self.sub.uuid}").status_code, 200)

    def test_other_agent_404(self):
        self.assertEqual(self.get(self.agent, f"submissions/{self.sub.uuid}").status_code, 404)
