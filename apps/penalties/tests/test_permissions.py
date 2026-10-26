from django.utils import timezone

from apps.penalties.permissions import (
    can_add, can_manage_types, can_penalize, can_void, penalty_targets, visible_penalties)
from apps.penalties.tests.factories import make_penalty, make_user
from apps.users.models import Department
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes


class PenaltyPermissionTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.objects.create(name="Other")
        self.hr = make_user("hr", UserTypes.HR, self.department)
        self.manager = make_user("mgr", UserTypes.MANAGER, self.department)
        self.other_manager = make_user("mgr2", UserTypes.MANAGER, self.other_dept)
        self.nodept_manager = make_user("mgr3", UserTypes.MANAGER)

    def test_manager_same_department_can_penalize(self):
        self.assertTrue(can_penalize(self.manager, self.agent))

    def test_manager_other_department_cannot(self):
        self.assertFalse(can_penalize(self.other_manager, self.agent))

    def test_manager_inactive_target_cannot(self):
        self.agent.is_active = False
        self.assertFalse(can_penalize(self.manager, self.agent))

    def test_agent_cannot(self):
        self.assertFalse(can_penalize(self.agent, self.manager))

    def test_hr_can_penalize_anyone_but_self(self):
        self.assertTrue(can_penalize(self.hr, self.agent))
        self.assertTrue(can_penalize(self.hr, self.other_manager))
        self.assertFalse(can_penalize(self.hr, self.hr))

    def test_owner_and_superuser_can_penalize_self(self):
        self.assertTrue(can_penalize(self.superuser, self.superuser))
        owner = make_user("owner", UserTypes.OWNER)
        self.assertTrue(can_penalize(owner, owner))

    def test_manager_cannot_penalize_self(self):
        self.assertFalse(can_penalize(self.manager, self.manager))

    def test_void_creator_ok(self):
        p = make_penalty(self.agent, self.manager)
        self.assertTrue(can_void(self.manager, p))

    def test_void_hr_ok(self):
        p = make_penalty(self.agent, self.manager)
        self.assertTrue(can_void(self.hr, p))

    def test_void_other_manager_denied(self):
        other = make_user("mgr4", UserTypes.MANAGER, self.department)
        p = make_penalty(self.agent, self.manager)
        self.assertFalse(can_void(other, p))

    def test_void_penalised_user_denied(self):
        p = make_penalty(self.hr, self.superuser)
        self.assertFalse(can_void(self.hr, p))
        self.assertTrue(can_void(self.superuser, p))

    def test_void_already_voided_false(self):
        p = make_penalty(self.agent, self.manager, voided_at=timezone.now())
        self.assertFalse(can_void(self.hr, p))

    def test_visible_penalties_per_role(self):
        mine = make_penalty(self.manager, self.hr)
        dept = make_penalty(self.agent, self.hr)
        elsewhere = make_penalty(self.other_manager, self.hr)
        self.assertEqual(set(visible_penalties(self.agent)), {dept})
        self.assertEqual(set(visible_penalties(self.manager)), {mine, dept})
        self.assertEqual(set(visible_penalties(self.hr)), {mine, dept, elsewhere})

    def test_manager_sees_inactive_department_user_history(self):
        p = make_penalty(self.agent, self.hr)
        self.agent.is_active = False
        self.agent.save()
        self.assertIn(p, visible_penalties(self.manager))

    def test_manager_without_department_sees_own_only_and_cannot_add(self):
        own = make_penalty(self.nodept_manager, self.hr)
        make_penalty(self.agent, self.hr)
        self.assertEqual(list(visible_penalties(self.nodept_manager)), [own])
        self.assertFalse(can_add(self.nodept_manager))
        self.assertFalse(penalty_targets(self.nodept_manager).exists())

    def test_penalty_targets(self):
        self.assertEqual(set(penalty_targets(self.manager)), {self.agent, self.superuser, self.hr})
        self.assertNotIn(self.hr, penalty_targets(self.hr))
        self.assertIn(self.superuser, penalty_targets(self.superuser))
        self.assertTrue(can_add(self.manager) and can_add(self.hr))
        self.assertFalse(can_add(self.agent))
        self.assertTrue(can_manage_types(self.hr))
        self.assertFalse(can_manage_types(self.manager))
