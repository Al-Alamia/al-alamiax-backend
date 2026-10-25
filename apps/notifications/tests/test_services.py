from rest_framework.exceptions import PermissionDenied

from apps.notifications.models import Notification, NotificationRecipient
from apps.notifications.services import notify, resolve_audience
from apps.users.models import Department, Project, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes


class ServiceTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.objects.create(name="Other Department")
        self.other_project = Project.objects.create(name="Other Project")
        self.manager = self._make("manager", UserTypes.MANAGER)
        self.hr = self._make("hr", UserTypes.HR)
        self.inactive = self._make("inactive", UserTypes.AGENT, is_active=False)
        self.outsider = self._make(
            "outsider", UserTypes.AGENT, department=self.other_dept, project=self.other_project
        )

    def _make(self, username, role, **kw):
        kw.setdefault("department", self.department)
        kw.setdefault("project", self.project)
        return User.objects.create_user(
            username=username, password="pass123", email=f"{username}@test.com", role=role, **kw
        )

    def test_notify_rejects_unsafe_links(self):
        for bad in ["javascript:alert(1)", "https://evil.com", "//evil.com", "/\\evil"]:
            with self.assertRaises(ValueError, msg=bad):
                notify([self.hr], "hi", link=bad)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertTrue(notify([self.hr], "hi", link="/requests?uuid=x").pk)

    def test_departments_expand_to_active_members_distinct(self):
        qs = resolve_audience(
            self.hr, departments=[self.department.pk, str(self.department.pk)], users=[self.agent, self.agent.pk]
        )
        ids = list(qs.values_list("pk", flat=True))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            set(ids), {self.superuser.pk, self.agent.pk, self.manager.pk}
        )
        self.assertNotIn(self.inactive.pk, ids)

    def test_sender_excluded(self):
        qs = resolve_audience(self.hr, everyone=True)
        self.assertNotIn(self.hr.pk, qs.values_list("pk", flat=True))
        expected = set(User.objects.filter(is_active=True).exclude(pk=self.hr.pk).values_list("pk", flat=True))
        self.assertEqual(set(qs.values_list("pk", flat=True)), expected)

    def test_roles(self):
        qs = resolve_audience(self.hr, roles=["AGENT"])
        self.assertEqual(set(qs), set(User.objects.filter(is_active=True, role=UserTypes.AGENT)))
        self.assertNotIn(self.inactive, qs)

    def test_manager_own_department_and_project_ok(self):
        qs = resolve_audience(self.manager, departments=[self.department])
        self.assertIn(self.agent, qs)
        qs = resolve_audience(self.manager, projects=[self.project.pk])
        self.assertIn(self.agent, qs)
        self.assertNotIn(self.manager, qs)

    def test_manager_scope_rejections(self):
        for kwargs in (
            {"users": [self.outsider]},
            {"departments": [self.other_dept]},
            {"roles": ["AGENT"]},
            {"everyone": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(PermissionDenied):
                    resolve_audience(self.manager, **kwargs)

    def test_manager_without_scope_denied(self):
        lone = self._make("lone", UserTypes.MANAGER, department=None, project=None)
        with self.assertRaises(PermissionDenied):
            resolve_audience(lone, users=[self.agent])

    def test_system_sender_unrestricted(self):
        qs = resolve_audience(None, everyone=True)
        self.assertEqual(set(qs), set(User.objects.filter(is_active=True)))

    def test_notify_creates_one_recipient_per_user(self):
        n = notify(
            [self.agent, self.agent, self.manager], "hi", title="T", link="/x", sender=self.hr,
            audience={"everyone": False},
        )
        self.assertEqual(NotificationRecipient.objects.filter(notification=n).count(), 2)
        self.assertFalse(NotificationRecipient.objects.filter(notification=n, read_at__isnull=False).exists())
        n.refresh_from_db()
        self.assertEqual((n.message, n.title, n.link, n.sender, n.kind), ("hi", "T", "/x", self.hr, "manual"))
        self.assertEqual(n.audience, {"everyone": False})

    def test_notify_rejects_empty(self):
        with self.assertRaises(ValueError):
            notify([], "x")
        with self.assertRaises(ValueError):
            notify([self.agent], "  ")
        self.assertEqual(Notification.objects.count(), 0)
