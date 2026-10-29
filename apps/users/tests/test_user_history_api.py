from datetime import date

from apps.payroll_config.services import set_basic
from apps.users.models import Department, Profile, UpdateHistory
from apps.users.types import UserTypes
from .base import BaseUserTestCase
from .user_admin_factories import make_user


class UserHistoryApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.objects.create(name="Other")
        self.hr = make_user("hr1", UserTypes.HR)
        self.manager = make_user("mgr1", UserTypes.MANAGER, department=self.department)
        self.other_manager = make_user("mgr2", UserTypes.MANAGER, department=self.other_dept)
        UpdateHistory.objects.all().delete()

    def url(self, user, kind="history"):
        return f"/api/users/admin/users/{user.uuid}/{kind}"

    def patch(self, **data):
        return self.client.patch(f"/api/users/admin/users/{self.agent.uuid}", data, format="json")

    def test_two_patches_newest_first_with_diffs(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.patch(title="Senior").status_code, 200)
        self.assertEqual(self.patch(title="Lead", first_name="Ann").status_code, 200)
        r = self.client.get(self.url(self.agent))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 2)
        newest, oldest = r.data["results"]
        self.assertEqual(set(newest), {"id", "at", "by", "model", "object", "changes"})
        self.assertEqual((newest["model"], newest["object"]), ("User", str(self.agent.uuid)))
        self.assertEqual(newest["by"], {"uuid": str(self.hr.uuid), "name": self.hr.username})
        self.assertEqual({(c["field"], c["old"], c["new"]) for c in newest["changes"]},
                         {("title", "Senior", "Lead"), ("first_name", "", "Ann")})
        self.assertEqual([(c["field"], c["new"]) for c in oldest["changes"]], [("title", "Senior")])

    def test_redacted_fields_never_appear(self):
        self.authenticate_as(self.hr)
        self.client.post(f"/api/users/{self.agent.uuid}/set_password", {"password": "NewPass1!x"}, format="json")
        self.patch(title="T")
        self.agent.refresh_from_db()
        self.agent.save()  # touches updated_at
        entries = self.client.get(self.url(self.agent)).data["results"]
        self.assertTrue(all(e["changes"] for e in entries))
        fields = {c["field"] for e in entries for c in e["changes"]}
        self.assertIn("title", fields)
        self.assertFalse(fields & {"password", "last_login", "updated_at", "created_at"})
        self.assertFalse([f for f in fields if "password" in f])

    def test_profile_change_in_user_history(self):
        self.authenticate_as(self.agent)
        self.client.patch("/api/users/me/profile", {"about": "hello"})
        self.authenticate_as(self.hr)
        results = self.client.get(self.url(self.agent)).data["results"]
        entry = next(e for e in results if e["model"] == "Profile")
        self.assertEqual(entry["by"]["uuid"], str(self.agent.uuid))
        self.assertIn(("about", "", "hello"), [(c["field"], c["old"], c["new"]) for c in entry["changes"]])

    def test_basic_salary_changes_included(self):
        set_basic(self.agent, date.today(), 400, "", self.hr)
        set_basic(self.agent, date.today(), 500, "", self.hr)
        self.authenticate_as(self.hr)
        results = self.client.get(self.url(self.agent)).data["results"]
        entry = next(e for e in results if e["model"] == "BasicSalary")
        self.assertIn(("amount", "400.00", "500.00"), [(c["field"], c["old"], c["new"]) for c in entry["changes"]])

    def test_other_users_excluded(self):
        peer = make_user("peer", UserTypes.AGENT, department=self.department)
        peer.title = "x"
        peer.save()
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get(self.url(self.agent)).data["count"], 0)

    def test_pagination(self):
        self.authenticate_as(self.hr)
        for i in range(17):
            self.patch(title=f"t{i}")
        r = self.client.get(self.url(self.agent))
        self.assertEqual((r.data["count"], len(r.data["results"])), (17, 15))
        self.assertEqual(len(self.client.get(self.url(self.agent) + "?page=2").data["results"]), 2)

    def test_actions_lists_rows_by_actor(self):
        self.authenticate_as(self.hr)
        self.patch(title="A")
        self.client.patch(f"/api/users/admin/users/{self.manager.uuid}", {"title": "M"}, format="json")
        r = self.client.get(self.url(self.hr, "actions"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([(e["model"], e["object"]) for e in r.data["results"]],
                         [("User", str(self.manager.uuid)), ("User", str(self.agent.uuid))])
        self.assertTrue(all(e["by"]["uuid"] == str(self.hr.uuid) for e in r.data["results"]))
        self.assertEqual(r.data["results"][0]["changes"][0]["new"], "M")
        self.assertEqual(self.client.get(self.url(self.agent, "actions")).data["count"], 0)

    def test_history_authz(self):
        self.authenticate_as(self.manager)
        for kind in ("history", "actions"):
            r = self.client.get(self.url(self.agent, kind))
            self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"), kind)
        self.authenticate_as(self.other_manager)
        self.assertEqual(self.client.get(self.url(self.agent)).status_code, 404)
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(self.url(self.agent)).status_code, 403)
        self.assertEqual(self.client.get(self.url(self.hr)).status_code, 404)

    def test_login_only_save_creates_no_entry(self):
        from django.utils import timezone
        self.agent.last_login = timezone.now()
        self.agent.save()
        self.agent.save()  # no-op
        self.assertEqual(UpdateHistory.objects.count(), 0)
        self.authenticate_as(self.hr)
        self.patch(title="X")
        self.assertEqual(self.client.get(self.url(self.agent)).data["count"], 1)

    def test_real_change_still_recorded(self):
        self.agent.title = "Changed"
        self.agent.save()
        self.assertEqual(UpdateHistory.objects.count(), 1)
