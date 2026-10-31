import datetime as dt

from rest_framework.exceptions import PermissionDenied

from apps.attendance.models import PeriodClose
from apps.subscriptions import permissions as perms
from apps.subscriptions.models import Subscription
from apps.subscriptions.tests.factories import (
    assign, make_lead, make_payment, make_subscription, marketing_dept, sales_dept,
)
from apps.teams.models import Team
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = dt.date


def mk(username, role, dept):
    return User.objects.create_user(
        username=username, password="x", email=f"{username}@t.com", role=role,
        project=None, department=dept,
    )


class SubscriptionPermissionTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        sales, mkt = sales_dept(), marketing_dept()
        self.manager = mk("s_manager", UserTypes.MANAGER, sales)
        self.leader = mk("s_leader", UserTypes.AGENT, sales)
        self.a = mk("s_a", UserTypes.AGENT, sales)
        self.c = mk("s_c", UserTypes.AGENT, sales)
        self.b = mk("s_b", UserTypes.AGENT, sales)
        self.m = mk("m_user", UserTypes.AGENT, mkt)
        self.hr = mk("hr_user", UserTypes.HR, self.department)
        self.mkt_manager = mk("m_manager", UserTypes.MANAGER, mkt)
        team = Team.objects.create(name="T", department=sales, leader=self.leader)
        team.agents.add(self.a)

        self.l1 = make_lead(self.m)
        assign(self.l1, self.a, "sales")
        assign(self.l1, self.c, "cs")
        self.past = mk("s_past", UserTypes.AGENT, sales)
        assign(self.l1, self.past, "sales", active=False)
        self.s1 = make_subscription(self.l1, self.a)

        # another lead the leader's team does not own, sold by A (no longer assigned)
        self.l2 = make_lead(self.m)
        assign(self.l2, self.b, "sales")
        self.s2 = make_subscription(self.l2, self.a)
        # unrelated lead
        self.l3 = make_lead(self.m)
        assign(self.l3, self.b, "sales")
        self.s3 = make_subscription(self.l3, self.b)

    def ids(self, user):
        return set(perms.scope_subscriptions(user, Subscription.objects.all()))

    def test_scope(self):
        everything = {self.s1, self.s2, self.s3}
        self.assertEqual(self.ids(self.superuser), everything)
        self.assertEqual(self.ids(self.manager), everything)
        self.assertEqual(self.ids(self.leader), {self.s1, self.s2})
        self.assertEqual(self.ids(self.a), {self.s1, self.s2})
        self.assertEqual(self.ids(self.c), {self.s1})
        self.assertEqual(self.ids(self.b), {self.s2, self.s3})
        self.assertNotIn(self.s1, self.ids(self.b))

    def test_scope_denied(self):
        for u in (self.m, self.hr, self.mkt_manager):
            self.assertFalse(perms.has_access(u))
            with self.assertRaises(PermissionDenied) as cm:
                perms.scope_subscriptions(u, Subscription.objects.all())
            self.assertEqual(str(cm.exception.detail), perms.DENIED_MESSAGE)

    def test_hidden_lead_scope(self):
        self.l1.is_hidden = True
        self.l1.save()
        self.assertIn(self.s1, self.ids(self.superuser))
        self.assertIn(self.s1, self.ids(self.manager))
        self.assertIn(self.s1, self.ids(self.a))  # seller sees own
        self.assertNotIn(self.s1, self.ids(self.c))  # lead-scope only, hidden excluded

    def test_lead_can(self):
        self.assertEqual(perms.lead_can(self.a, self.l1), {"view": True, "create": True, "choose_seller": False})
        self.assertTrue(perms.lead_can(self.c, self.l1)["create"])
        self.assertFalse(perms.lead_can(self.b, self.l1)["create"])
        self.assertTrue(perms.lead_can(self.leader, self.l1)["choose_seller"])
        self.assertTrue(perms.lead_can(self.manager, self.l1)["choose_seller"])
        self.assertEqual(perms.lead_can(self.m, self.l1), {"view": False, "create": False, "choose_seller": False})

    def test_hidden_lead_cannot_create(self):
        self.l1.is_hidden = True
        self.l1.save()
        for u in (self.superuser, self.manager, self.leader, self.a, self.c):
            self.assertFalse(perms.lead_can(u, self.l1)["create"])
        self.assertTrue(perms.lead_can(self.superuser, self.l1)["view"])
        self.assertTrue(perms.lead_can(self.manager, self.l1)["view"])
        self.assertFalse(perms.lead_can(self.a, self.l1)["view"])

    def test_row_can(self):
        self.assertEqual(perms.row_can(self.a, self.s1),
                         {"edit": False, "cancel": False, "delete": False, "add_payment": True})
        r = perms.row_can(self.leader, self.s1)
        self.assertTrue(r["edit"] and r["cancel"] and r["delete"])
        make_payment(self.s1, "100", D(2026, 10, 1))
        self.assertFalse(perms.row_can(self.leader, self.s1)["delete"])
        from django.utils import timezone
        self.s1.cancelled_at = timezone.now()
        r = perms.row_can(self.leader, self.s1)
        self.assertFalse(r["edit"] or r["cancel"])
        self.assertFalse(perms.row_can(self.a, self.s1)["add_payment"])

    def test_payment_can(self):
        p = make_payment(self.s1, "100", D(2026, 10, 1), recorded_by=self.a)
        self.assertTrue(perms.payment_can(self.a, p)["edit"])
        self.assertFalse(perms.payment_can(self.b, p)["edit"])
        self.assertTrue(perms.payment_can(self.leader, p)["delete"])
        PeriodClose.objects.create(period="2026-09", start=D(2026, 8, 26), end=D(2026, 9, 25),
                                   closed_by=self.superuser, closed_at=dt.datetime(2026, 10, 20, 12))
        q = make_payment(self.s1, "100", D(2026, 9, 10), recorded_by=self.a)
        self.assertEqual(perms.payment_can(self.superuser, q), {"edit": False, "delete": False})

    def test_seller_choices(self):
        self.assertEqual(list(perms.seller_choices(self.l1)), [self.a, self.c, self.past])
