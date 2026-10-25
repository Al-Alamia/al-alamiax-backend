from datetime import datetime, timedelta
from unittest.mock import patch

from apps.notifications.models import Notification, NotificationRecipient
from apps.notifications.services import notify
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

B = "/api/notifications/"
NOW = datetime(2026, 10, 25, 12, 0)


class SendApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        mk = lambda name, role, **kw: User.objects.create_user(
            username=name, password="pass123", email=f"{name}@test.com", role=role, **kw)
        self.hr = mk("hr", UserTypes.HR, project=self.project, department=self.department)
        self.hr2 = mk("hr2", UserTypes.HR)
        self.manager = mk("mgr", UserTypes.MANAGER, project=self.project, department=self.department)
        self.agent2 = mk("agent2", UserTypes.AGENT, project=self.project, department=self.department)
        self.inactive = mk("inactive", UserTypes.AGENT, project=self.project, department=self.department)
        User.objects.filter(pk=self.inactive.pk).update(is_active=False)
        self.other_dept = Department.objects.create(name="Other")
        p = patch("apps.notifications.views._now", return_value=NOW)
        p.start()
        self.addCleanup(p.stop)

    def _send(self, **body):
        body.setdefault("message", "hello")
        return self.client.post(B + "send", body, format="json")

    def test_agent_cannot_send(self):
        self.authenticate_as(self.agent)
        r = self._send(users=[str(self.agent2.pk)])
        self.assertEqual(r.status_code, 403)

    def test_hr_sends_to_department(self):
        self.authenticate_as(self.hr)
        r = self._send(departments=[str(self.department.pk)], sender=str(self.agent.pk))
        self.assertEqual(r.status_code, 201, r.data)
        n = Notification.objects.get(pk=r.data["uuid"])
        self.assertEqual(n.sender, self.hr)
        self.assertEqual(n.audience, {"departments": [str(self.department.pk)]})
        got = set(n.recipients.values_list("user__username", flat=True))
        self.assertEqual(got, {"superuser", "agent", "mgr", "agent2"})

    def test_send_rejects_non_object_body(self):
        self.authenticate_as(self.hr)
        r = self.client.post(B + "send", [1, 2], format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_body"))

    def test_send_link_validation(self):
        self.authenticate_as(self.hr)
        t = [str(self.agent.pk)]
        for bad in ["javascript:alert(1)", "https://evil.com", "//evil.com", "/\\evil", "rel/path"]:
            r = self._send(users=t, link=bad)
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_body"), bad)
        self.assertEqual(self._send(users=t, link="/requests?uuid=x").status_code, 201)
        self.assertEqual(self._send(users=t, link="").status_code, 201)

    def test_send_validation(self):
        self.authenticate_as(self.hr)
        t = [str(self.agent.pk)]
        self.assertEqual(self.client.post(B + "send", {"users": t}, format="json").status_code, 400)
        self.assertEqual(self._send(users=t, message="x" * 1001).status_code, 400)
        self.assertEqual(self._send().status_code, 400)
        self.assertEqual(self._send(users=t, expires_at="2026-10-25T11:00:00").status_code, 400)
        self.assertEqual(self._send(users=t, expires_at="nope").status_code, 400)
        r = self._send(users=["bad"])
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_target"))
        r = self._send(roles=["WIZARD"])
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_target"))
        self.assertEqual(Notification.objects.count(), 0)

    def test_send_resolving_to_nobody(self):
        self.authenticate_as(self.hr)
        self.assertEqual(self._send(users=[str(self.inactive.pk)]).status_code, 400)

    def test_manager_out_of_scope_403(self):
        self.authenticate_as(self.manager)
        r = self._send(departments=[str(self.other_dept.pk)])
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))

    def test_manager_without_scope_403(self):
        m = User.objects.create_user(username="m2", password="x", email="m2@test.com", role=UserTypes.MANAGER)
        self.authenticate_as(m)
        self.assertEqual(self._send(users=[str(self.agent.pk)]).status_code, 403)
        self.assertEqual(self._send(departments=[str(self.department.pk)]).status_code, 403)

    def test_sent_lists_own_with_counts(self):
        self.authenticate_as(self.manager)
        r = self._send(users=[str(self.agent.pk), str(self.agent2.pk)])
        self.assertEqual(r.status_code, 201, r.data)
        notify([self.agent], "hr one", sender=self.hr)
        NotificationRecipient.objects.filter(
            notification__pk=r.data["uuid"], user=self.agent).update(read_at=NOW)
        r = self.client.get(B + "sent")
        self.assertEqual(r.data["count"], 1)
        item = r.data["results"][0]
        self.assertEqual((item["recipients_count"], item["read_count"]), (2, 1))
        self.assertEqual(item["audience"]["users"][0].keys(), {"uuid", "name"})
        self.assertEqual(item["sender"]["uuid"], str(self.manager.pk))
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.get(B + "sent").data["count"], 2)

    def test_recipients_visible_to_sender_and_owner_only(self):
        n = notify([self.agent], "m", sender=self.hr)
        url = f"{B}sent/{n.pk}/recipients"
        self.authenticate_as(self.hr2)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.authenticate_as(self.hr)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["read_at"], None)
        self.assertEqual(r.data[0]["user"]["uuid"], str(self.agent.pk))
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_retract(self):
        n = notify([self.agent], "m", sender=self.hr)
        url = f"{B}sent/{n.pk}/retract"
        self.authenticate_as(self.hr2)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.authenticate_as(self.hr)
        r = self.client.post(url)
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.data["retracted_at"])
        first = Notification.objects.get(pk=n.pk).retracted_at
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(Notification.objects.get(pk=n.pk).retracted_at, first)
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(B + "inbox").data["count"], 0)
