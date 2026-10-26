from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.commission.models import UserCommissionDetails
from apps.users.models import Department, Profile, UpdateHistory, User
from apps.users.types import UserTypes
from .base import BaseUserTestCase
from .user_admin_factories import make_user

STRONG = "Zx9!kLmQ47pw"
BASE = "/api/users/admin/users"


class AdminUsersTestBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.objects.create(name="Other")
        self.hr = make_user("hr1", UserTypes.HR)
        self.owner = make_user("owner1", UserTypes.OWNER)
        self.manager = make_user("mgr1", UserTypes.MANAGER, department=self.department)
        self.outsider = make_user("out1", UserTypes.AGENT, department=self.other_dept)

    def payload(self, **kw):
        data = {"username": "newbie", "password": STRONG, "first_name": "New", "last_name": "Bie",
                "role": "AGENT", "department": str(self.department.uuid),
                "project": str(self.project.uuid), "title": "Rep", "basic_salary": 5000}
        data.update(kw)
        return data

    def counts(self):
        return (User.objects.count(), Profile.objects.count(), UserCommissionDetails.objects.count())


class ListTests(AdminUsersTestBase):
    def usernames(self, resp):
        return {u["username"] for u in resp.data["results"]}

    def test_hr_lists_all_but_superuser_and_owner(self):
        self.authenticate_as(self.hr)
        r = self.client.get(BASE)
        self.assertEqual(r.status_code, 200)
        names = self.usernames(r)
        self.assertIn("agent", names)
        self.assertNotIn("owner1", names)
        self.assertNotIn("superuser", names)
        self.assertTrue(r.data["can_create"])
        self.assertEqual(r.data["assignable_roles"], ["AGENT", "MANAGER", "HR"])

    def test_hr_list_hides_owner(self):
        self.authenticate_as(self.hr)
        self.assertNotIn("owner1", self.usernames(self.client.get(BASE)))

    def test_owner_sees_owners_and_can_assign_owner(self):
        self.authenticate_as(self.owner)
        r = self.client.get(BASE)
        self.assertIn("owner1", self.usernames(r))
        self.assertIn("OWNER", r.data["assignable_roles"])

    def test_manager_sees_own_department_read_only(self):
        self.authenticate_as(self.manager)
        r = self.client.get(BASE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.usernames(r), {"agent", "mgr1"})
        self.assertFalse(r.data["can_create"])
        self.assertEqual(r.data["assignable_roles"], [])
        self.assertFalse(r.data["results"][0]["can"]["edit"])

    def test_agent_forbidden(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(BASE).status_code, 403)
        self.assertEqual(self.client.get(BASE + "/options").status_code, 403)

    def test_filters(self):
        User.objects.filter(pk=self.agent.pk).update(is_active=False)
        self.authenticate_as(self.hr)
        self.assertEqual(self.usernames(self.client.get(BASE + "?is_active=false")), {"agent"})
        self.assertNotIn("agent", self.usernames(self.client.get(BASE + "?is_active=true")))
        self.assertEqual(self.usernames(self.client.get(BASE + "?role=MANAGER")), {"mgr1"})
        self.assertEqual(self.usernames(self.client.get(BASE + f"?department={self.other_dept.uuid}")), {"out1"})
        self.assertEqual(self.usernames(self.client.get(BASE + "?search=OUT")), {"out1"})
        self.assertEqual(self.client.get(BASE + "?department=nope").data["count"], 0)

    def test_item_shape_has_no_password(self):
        self.authenticate_as(self.hr)
        item = self.client.get(BASE + "?search=agent").data["results"][0]
        self.assertEqual(set(item), {
            "uuid", "username", "name", "first_name", "last_name", "role", "title", "is_active",
            "crm_username", "fp_id", "department", "project", "picture", "can"})
        self.assertEqual(item["department"]["name"], "Test Department")
        self.assertIsNone(item["picture"])
        self.assertEqual(set(item["can"]), {"edit", "deactivate", "manage_devices"})

    def test_options_shape_and_cap(self):
        self.authenticate_as(self.hr)
        r = self.client.get(BASE + "/options")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data[0]), {"uuid", "name", "username", "role", "department"})
        self.assertNotIn("owner1", {o["username"] for o in r.data})
        for i in range(205):
            make_user(f"bulk{i}")
        self.assertEqual(len(self.client.get(BASE + "/options").data), 200)


class CreateTests(AdminUsersTestBase):
    def test_create_201_with_profile_and_basic(self):
        self.authenticate_as(self.hr)
        r = self.client.post(BASE, self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        user = User.objects.get(username="newbie")
        self.assertTrue(user.check_password(STRONG))
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertEqual(UserCommissionDetails.objects.get(user=user).basic, 5000)
        self.assertEqual(r.data["basic_salary"], 5000)
        self.assertEqual(r.data["name"], "New Bie")
        self.assertNotIn(STRONG, r.content.decode())
        self.assertNotIn("pbkdf2", r.content.decode())
        self.assertEqual(user.department, self.department)

    def test_create_atomic_on_duplicate_username(self):
        self.authenticate_as(self.hr)
        before = self.counts()
        r = self.client.post(BASE, self.payload(username="agent"), format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate_username"))
        self.assertEqual(self.counts(), before)

    def test_create_atomic_on_duplicate_fp_id(self):
        User.objects.filter(pk=self.agent.pk).update(fp_id="77")
        self.authenticate_as(self.hr)
        before = self.counts()
        r = self.client.post(BASE, self.payload(fp_id="77"), format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate_fp_id"))
        self.assertEqual(self.counts(), before)

    def test_create_atomic_on_invalid_password(self):
        self.authenticate_as(self.hr)
        before = self.counts()
        for pw in ("123", "12345678", None):
            r = self.client.post(BASE, self.payload(password=pw), format="json")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        self.assertEqual(self.counts(), before)

    def test_unknown_department_invalid(self):
        self.authenticate_as(self.hr)
        r = self.client.post(BASE, self.payload(department="00000000-0000-0000-0000-000000000000"), format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_bad_basic_salary_invalid(self):
        self.authenticate_as(self.hr)
        for bad in (-1, "abc", 1.5, True):
            r = self.client.post(BASE, self.payload(basic_salary=bad), format="json")
            self.assertEqual(r.status_code, 400, bad)

    def test_hr_create_owner_role_not_allowed(self):
        self.authenticate_as(self.hr)
        r = self.client.post(BASE, self.payload(role="OWNER"), format="json")
        self.assertEqual((r.status_code, r.data["type"]), (403, "role_not_allowed"))
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_owner_can_create_owner(self):
        self.authenticate_as(self.owner)
        self.assertEqual(self.client.post(BASE, self.payload(role="OWNER"), format="json").status_code, 201)

    def test_manager_and_agent_cannot_create(self):
        for u in (self.manager, self.agent):
            self.authenticate_as(u)
            self.assertEqual(self.client.post(BASE, self.payload(), format="json").status_code, 403)


class DetailTests(AdminUsersTestBase):
    def test_detail_shape(self):
        self.authenticate_as(self.hr)
        r = self.client.get(f"{BASE}/{self.agent.uuid}")
        self.assertEqual(r.status_code, 200)
        for key in ("phone", "telegram_id", "about", "basic_salary", "date_joined", "last_login",
                    "assignable_roles"):
            self.assertIn(key, r.data)
        self.assertEqual(set(r.data["can"]), {
            "edit", "deactivate", "manage_devices", "view_devices", "view_files", "manage_files",
            "view_history", "reset_password"})
        self.assertTrue(r.data["can"]["reset_password"])

    def test_detail_404_for_invisible(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get(f"{BASE}/{self.owner.uuid}").status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}/{self.superuser.uuid}").status_code, 404)
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(f"{BASE}/{self.outsider.uuid}").status_code, 404)

    def test_agent_views_self_only(self):
        self.authenticate_as(self.agent)
        r = self.client.get(f"{BASE}/{self.agent.uuid}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can"]["edit"])
        self.assertFalse(r.data["can"]["reset_password"])
        self.assertEqual(self.client.get(f"{BASE}/{self.outsider.uuid}").status_code, 404)

    def test_manager_reset_password_flag_mirrors_set_password(self):
        self.authenticate_as(self.manager)
        r = self.client.get(f"{BASE}/{self.agent.uuid}")
        self.assertTrue(r.data["can"]["reset_password"])
        self.assertFalse(r.data["can"]["edit"])


class PatchTests(AdminUsersTestBase):
    def test_patch_updates_and_records_actor(self):
        self.authenticate_as(self.hr)
        r = self.client.patch(f"{BASE}/{self.agent.uuid}", {"title": "Senior", "department": None}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.title, "Senior")
        self.assertIsNone(self.agent.department)
        self.assertTrue(UpdateHistory.objects.filter(
            model_uuid=self.agent.uuid, model_name="User", user=self.hr).exists())

    def test_patch_ignores_password(self):
        self.authenticate_as(self.hr)
        self.client.patch(f"{BASE}/{self.agent.uuid}", {"password": "hacked1X!", "title": "T"}, format="json")
        self.agent.refresh_from_db()
        self.assertTrue(self.agent.check_password("pass123"))

    def test_patch_duplicate_username(self):
        self.authenticate_as(self.hr)
        r = self.client.patch(f"{BASE}/{self.agent.uuid}", {"username": "mgr1"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate_username"))

    def test_patch_keeping_own_values_is_fine(self):
        self.authenticate_as(self.hr)
        r = self.client.patch(f"{BASE}/{self.agent.uuid}", {"username": "agent", "fp_id": ""}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_hr_cannot_promote_to_owner_via_patch(self):
        self.authenticate_as(self.hr)
        r = self.client.patch(f"{BASE}/{self.agent.uuid}", {"role": "OWNER"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (403, "role_not_allowed"))
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.role, UserTypes.AGENT)

    def test_hr_cannot_touch_owner(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.patch(f"{BASE}/{self.owner.uuid}", {"title": "x"}, format="json").status_code, 404)

    def test_self_role_change(self):
        self.authenticate_as(self.hr)
        r = self.client.patch(f"{BASE}/{self.hr.uuid}", {"role": "AGENT"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "self_change"))

    def test_self_edit_title_ok(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.patch(f"{BASE}/{self.hr.uuid}", {"title": "Boss"}, format="json").status_code, 200)

    def test_manager_and_agent_cannot_patch(self):
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.patch(f"{BASE}/{self.agent.uuid}", {"title": "x"}, format="json").status_code, 403)
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.patch(f"{BASE}/{self.agent.uuid}", {"title": "x"}, format="json").status_code, 403)


class ActiveTests(AdminUsersTestBase):
    def test_deactivate_revokes_refresh(self):
        refresh = RefreshToken.for_user(self.agent)
        self.authenticate_as(self.hr)
        r = self.client.post(f"{BASE}/{self.agent.uuid}/deactivate")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["is_active"])
        self.agent.refresh_from_db()
        self.assertFalse(self.agent.is_active)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists())

    def test_activate(self):
        User.objects.filter(pk=self.agent.pk).update(is_active=False)
        self.authenticate_as(self.hr)
        r = self.client.post(f"{BASE}/{self.agent.uuid}/activate")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["is_active"])

    def test_self_deactivate(self):
        self.authenticate_as(self.hr)
        r = self.client.post(f"{BASE}/{self.hr.uuid}/deactivate")
        self.assertEqual((r.status_code, r.data["type"]), (400, "self_change"))
        self.hr.refresh_from_db()
        self.assertTrue(self.hr.is_active)

    def test_manager_cannot_deactivate(self):
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.post(f"{BASE}/{self.agent.uuid}/deactivate").status_code, 403)

    def test_old_route_removed(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get("/api/users/user").status_code, 404)
