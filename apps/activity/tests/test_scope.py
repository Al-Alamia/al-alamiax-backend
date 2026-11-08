from apps.activity.models import ActivityEvent
from apps.activity.permissions import (
    can_view_activity, scope_user_ids, scope_users, visible_events,
)
from apps.activity.services.events import record_event
from apps.activity.tests.helpers import ScopeFixtureMixin
from apps.users.tests.base import BaseUserTestCase


class ScopeTests(ScopeFixtureMixin, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.make_scope_fixture()

    def ids(self, viewer):
        return set(visible_events(viewer).values_list("pk", flat=True))

    def test_agent_cannot_view(self):
        self.assertFalse(can_view_activity(self.other_agent))

    def test_manager_leader_hr_can_view(self):
        for u in (self.manager, self.leader, self.hr):
            self.assertTrue(can_view_activity(u))

    def test_manager_sees_department_not_other(self):
        a = record_event(self.superuser, "request.approved", subject=self.agent)
        b = record_event(self.superuser, "request.approved", subject=self.other_agent)
        c = record_event(self.agent, "request.submitted")
        d = record_event(self.manager, "request.approved", subject=self.other_agent)
        ids = self.ids(self.manager)
        self.assertIn(a.pk, ids)
        self.assertNotIn(b.pk, ids)
        self.assertIn(c.pk, ids)
        self.assertIn(d.pk, ids)

    def test_leader_sees_team_members(self):
        a = record_event(self.superuser, "request.approved", subject=self.agent)
        b = record_event(self.superuser, "request.approved", subject=self.other_agent)
        ids = self.ids(self.leader)
        self.assertIn(a.pk, ids)
        self.assertNotIn(b.pk, ids)

    def test_hr_sees_all_but_treasury(self):
        e = record_event(self.superuser, "entry.added")
        r = record_event(self.superuser, "request.approved", subject=self.other_agent)
        self.assertNotIn(e.pk, self.ids(self.hr))
        self.assertIn(r.pk, self.ids(self.hr))
        self.assertIn(e.pk, self.ids(self.superuser))

    def test_manager_hidden_payroll(self):
        e = record_event(self.superuser, "salary.given", subject=self.agent)
        self.assertNotIn(e.pk, self.ids(self.manager))
        self.assertIn(e.pk, self.ids(self.hr))

    def test_scope_users_excludes_viewer(self):
        for u in (self.manager, self.hr, self.leader):
            self.assertNotIn(u.pk, set(scope_users(u).values_list("pk", flat=True)))
        self.assertIsNone(scope_user_ids(self.hr))
        self.assertNotIn(self.manager.pk, scope_user_ids(self.manager))
        self.assertIn(self.agent.pk, scope_user_ids(self.manager))

    def test_manager_own_payroll_event_hidden(self):
        for subj in (self.agent, None):
            e = record_event(self.manager, "salary.given", subject=subj)
            self.assertNotIn(e.pk, self.ids(self.manager))

    def test_hr_own_treasury_event_hidden(self):
        e = record_event(self.hr, "entry.added")
        self.assertNotIn(e.pk, self.ids(self.hr))


class SensitiveScopeTests(ScopeFixtureMixin, BaseUserTestCase):
    VERBS = ("advance.requested", "penalty.created", "file.uploaded")

    def setUp(self):
        super().setUp()
        self.make_scope_fixture()

    def ids(self, viewer):
        return set(visible_events(viewer).values_list("pk", flat=True))

    def test_leader_does_not_see_sensitive(self):
        for v in self.VERBS:
            e = record_event(self.superuser, v, subject=self.agent)
            self.assertNotIn(e.pk, self.ids(self.leader), v)
        plain = record_event(self.superuser, "request.approved", subject=self.agent)
        self.assertIn(plain.pk, self.ids(self.leader))

    def test_manager_sees_sensitive(self):
        for v in self.VERBS:
            e = record_event(self.superuser, v, subject=self.agent)
            self.assertIn(e.pk, self.ids(self.manager), v)

    def test_actor_sees_own(self):
        for v in self.VERBS:
            e = record_event(self.leader, v, subject=self.agent)
            self.assertIn(e.pk, self.ids(self.leader), v)

    def test_hr_sees_all(self):
        for v in self.VERBS:
            e = record_event(self.superuser, v, subject=self.agent)
            self.assertIn(e.pk, self.ids(self.hr), v)
