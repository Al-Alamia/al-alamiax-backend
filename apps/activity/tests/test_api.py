from datetime import datetime, timedelta

from apps.activity.models import ActivityEvent, PageView
from apps.activity.services.events import record_event
from apps.activity.tests.helpers import ScopeFixtureMixin
from apps.users.tests.base import BaseUserTestCase

BASE = "/api/activity/"
EVENT_KEYS = {"uuid", "created_at", "verb", "area", "actor", "subject",
              "target_type", "target_uuid", "target_label", "data"}


class ActivityApiTests(ScopeFixtureMixin, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.make_scope_fixture()

    def view(self, user, path, ts):
        return PageView.objects.create(user=user, path=path, started_at=ts, last_seen_at=ts)

    def test_heartbeat_204_and_row(self):
        self.authenticate_as(self.agent)
        r = self.client.post(BASE + "heartbeat", {"path": "/dashboard?x=1"}, format="json")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(PageView.objects.get(user=self.agent).path, "/dashboard")

    def test_heartbeat_400_bad_path(self):
        self.authenticate_as(self.agent)
        for body in ({}, {"path": "nope"}, {"path": 5}):
            r = self.client.post(BASE + "heartbeat", body, format="json")
            self.assertEqual(r.status_code, 400, body)

    def test_heartbeat_requires_auth(self):
        r = self.client.post(BASE + "heartbeat", {"path": "/x"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_access_flag(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(BASE + "access").json(), {"can_view": False})
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(BASE + "access").json(), {"can_view": True})

    def test_events_403_agent(self):
        self.authenticate_as(self.other_agent)
        for p in ("events", "presence", f"users/{self.agent.uuid}"):
            self.assertEqual(self.client.get(BASE + p).status_code, 403)

    def test_events_shape_and_order(self):
        a = record_event(self.superuser, "request.approved", subject=self.agent)
        b = record_event(self.agent, "request.submitted")
        ActivityEvent.objects.filter(pk=a.pk).update(created_at=datetime.now() - timedelta(hours=1))
        self.authenticate_as(self.manager)
        data = self.client.get(BASE + "events").json()
        self.assertEqual(data["count"], 2)
        self.assertEqual([r["uuid"] for r in data["results"]], [str(b.uuid), str(a.uuid)])
        self.assertEqual(set(data["results"][0]), EVENT_KEYS)
        self.assertEqual(set(data["results"][1]["actor"]), {"uuid", "name"})
        self.assertIsNone(data["results"][0]["subject"])

    def test_events_filters(self):
        a = record_event(self.superuser, "request.approved", subject=self.agent)
        b = record_event(self.agent, "request.submitted")
        self.authenticate_as(self.manager)
        uid = str(self.agent.uuid)

        def ids(qs):
            r = self.client.get(BASE + "events" + qs)
            self.assertEqual(r.status_code, 200)
            return {x["uuid"] for x in r.json()["results"]}

        self.assertEqual(ids(f"?user={uid}"), {str(a.uuid), str(b.uuid)})
        self.assertEqual(ids(f"?user={uid}&role=actor"), {str(b.uuid)})
        self.assertEqual(ids(f"?user={uid}&role=subject"), {str(a.uuid)})
        self.assertEqual(ids(f"?area={a.area}"), {str(a.uuid), str(b.uuid)} if b.area == a.area else {str(a.uuid)})
        self.assertEqual(self.client.get(BASE + "events?area=bogus").status_code, 400)
        self.assertEqual(self.client.get(BASE + "events?from=zzz").status_code, 400)
        yesterday = datetime.now() - timedelta(days=3)
        ActivityEvent.objects.filter(pk=a.pk).update(created_at=yesterday)
        d = yesterday.date().isoformat()
        self.assertEqual(ids(f"?from={d}&to={d}"), {str(a.uuid)})
        self.assertEqual(ids(f"?to={d}"), {str(a.uuid)})
        self.assertEqual(ids(f"?from={d}"), {str(a.uuid), str(b.uuid)})

    def test_events_area_filter_excludes_other_areas(self):
        a = record_event(self.superuser, "request.approved", subject=self.agent)
        record_event(self.superuser, "salary.given", subject=self.agent)
        self.authenticate_as(self.hr)
        r = self.client.get(BASE + f"events?area={a.area}").json()
        self.assertEqual({x["area"] for x in r["results"]}, {a.area})

    def test_events_user_out_of_scope_empty(self):
        record_event(self.other_agent, "request.submitted")
        record_event(self.superuser, "request.approved", subject=self.other_agent)
        self.authenticate_as(self.manager)
        r = self.client.get(BASE + f"events?user={self.other_agent.uuid}").json()
        self.assertEqual(r["count"], 0)

    def test_events_page_size_default_30(self):
        for _ in range(35):
            record_event(self.agent, "request.submitted")
        self.authenticate_as(self.manager)
        r = self.client.get(BASE + "events").json()
        self.assertEqual((r["count"], len(r["results"])), (35, 30))
        self.assertIsNotNone(r["next"])
        r = self.client.get(BASE + "events?page_size=5").json()
        self.assertEqual(len(r["results"]), 5)

    def test_presence_scoped_and_status_filter(self):
        now = datetime.now()
        self.agent.first_name, self.agent.last_name = "Zed", "Quux"
        self.agent.save()
        self.view(self.agent, "/a", now)
        self.authenticate_as(self.manager)
        r = self.client.get(BASE + "presence").json()["results"]
        names = {x["user"]["uuid"] for x in r}
        self.assertIn(str(self.agent.uuid), names)
        self.assertNotIn(str(self.other_agent.uuid), names)
        self.assertEqual(str(self.agent.uuid), r[0]["user"]["uuid"])
        on = self.client.get(BASE + "presence?status=online").json()["results"]
        self.assertEqual([x["user"]["uuid"] for x in on], [str(self.agent.uuid)])
        off = self.client.get(BASE + "presence?status=offline").json()["results"]
        self.assertNotIn(str(self.agent.uuid), {x["user"]["uuid"] for x in off})
        for s in (self.agent.username.upper(), "zed", "QUUX"):
            res = self.client.get(BASE + f"presence?search={s}").json()["results"]
            self.assertEqual([x["user"]["uuid"] for x in res], [str(self.agent.uuid)], s)

    def test_user_detail_404_out_of_scope(self):
        self.authenticate_as(self.manager)
        r = self.client.get(BASE + f"users/{self.other_agent.uuid}")
        self.assertEqual(r.status_code, 404)
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get(BASE + f"users/{self.other_agent.uuid}").status_code, 200)
        self.other_agent.is_active = False
        self.other_agent.save()
        self.assertEqual(self.client.get(BASE + f"users/{self.other_agent.uuid}").status_code, 200)

    def test_user_detail_shape(self):
        now = datetime.now()
        self.view(self.agent, "/old", now.replace(microsecond=0) - timedelta(minutes=10))
        pv = self.view(self.agent, "/new", now - timedelta(minutes=5))
        PageView.objects.filter(pk=pv.pk).update(last_seen_at=now - timedelta(minutes=4))
        record_event(self.agent, "request.submitted")
        self.authenticate_as(self.manager)
        r = self.client.get(BASE + f"users/{self.agent.uuid}").json()
        self.assertEqual(set(r), {"presence", "date", "page_views", "stats"})
        self.assertEqual(r["date"], now.date().isoformat())
        self.assertEqual([p["path"] for p in r["page_views"]], ["/new", "/old"])
        self.assertEqual(set(r["page_views"][0]), {"path", "started_at", "last_seen_at", "seconds"})
        self.assertEqual(r["page_views"][0]["seconds"], 60)
        self.assertEqual(r["stats"], {"today_seconds": 60, "pages_today": 2, "events_30d": 1})
        self.assertEqual(r["presence"]["user"]["uuid"], str(self.agent.uuid))
        day = (now - timedelta(days=2)).replace(hour=12)
        self.view(self.agent, "/past", day)
        r = self.client.get(BASE + f"users/{self.agent.uuid}?date={day.date()}").json()
        self.assertEqual(r["date"], str(day.date()))
        self.assertEqual([p["path"] for p in r["page_views"]], ["/past"])

    def test_user_detail_bad_date_400(self):
        self.authenticate_as(self.manager)
        r = self.client.get(BASE + f"users/{self.agent.uuid}?date=2026-13-45")
        self.assertEqual(r.status_code, 400)
