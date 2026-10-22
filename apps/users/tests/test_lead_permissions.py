from rest_framework.exceptions import PermissionDenied

from apps.users.lead_permissions import (
    active_assignment,
    capabilities,
    row_can,
    scope_queryset,
)
from apps.users.models import Lead
from apps.users.tests.lead_fixtures import LeadPipelineTestCase


def ids(qs):
    return {lead.uuid for lead in qs}


class LeadPermissionsTests(LeadPipelineTestCase):
    def scope(self, user, hidden=False):
        return scope_queryset(user, Lead.objects.all(), hidden=hidden)

    def test_scope_marketing_agent_sees_own(self):
        l1 = self.make_lead(self.mk_agent)
        self.make_lead(self.mk_leader)
        self.assertEqual(ids(self.scope(self.mk_agent)), {l1.uuid})

    def test_scope_marketing_leader_sees_team(self):
        l1 = self.make_lead(self.mk_agent)
        l2 = self.make_lead(self.mk_leader)
        self.make_lead(self.owner)
        self.assertEqual(ids(self.scope(self.mk_leader)), {l1.uuid, l2.uuid})

    def test_scope_sales_agent_sees_assigned_any_kind(self):
        a = self.make_lead(self.mk_agent)
        b = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent)
        self.assign(b, self.sales_agent, kind="cs")
        self.make_lead(self.mk_agent)
        self.assertEqual(ids(self.scope(self.sales_agent)), {a.uuid, b.uuid})

    def test_scope_sales_leader_team_and_unassigned(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent)
        u = self.make_lead(self.mk_agent)
        o = self.make_lead(self.mk_agent)
        self.assign(o, self.sales_agent2)
        self.assertEqual(ids(self.scope(self.sales_leader)), {a.uuid, u.uuid})

    def test_scope_sales_leader_cs_only_counts_as_unassigned(self):
        c = self.make_lead(self.mk_agent)
        self.assign(c, self.sales_agent2, kind="cs")
        self.assertEqual(ids(self.scope(self.sales_leader)), {c.uuid})

    def test_scope_no_duplicates(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent)
        self.assign(a, self.sales_agent, kind="cs")
        self.assertEqual(len(list(self.scope(self.sales_agent))), 1)

    def test_scope_admin_all_but_hidden(self):
        a = self.make_lead(self.mk_agent)
        h = self.make_lead(self.mk_agent, is_hidden=True)
        self.assertEqual(ids(self.scope(self.manager)), {a.uuid})
        self.assertEqual(ids(self.scope(self.manager, hidden=True)), {h.uuid})

    def test_scope_outsider_denied(self):
        with self.assertRaises(PermissionDenied):
            self.scope(self.outsider)

    def test_scope_hidden_denied_for_non_admin(self):
        with self.assertRaises(PermissionDenied):
            self.scope(self.mk_leader, hidden=True)

    def test_active_assignment(self):
        a = self.make_lead(self.mk_agent)
        s = self.assign(a, self.sales_agent)
        self.assertEqual(active_assignment(a, "sales"), s)
        self.assertIsNone(active_assignment(a, "cs"))

    def test_row_can_return(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent, days_ago=0)
        self.assertTrue(row_can(self.sales_agent, a)["return"])
        a.return_count = 1
        self.assertFalse(row_can(self.sales_agent, a)["return"])

    def test_row_can_return_window_closed(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent, days_ago=10)
        self.assertFalse(row_can(self.sales_agent, a)["return"])

    def test_row_can_marketing_note_only(self):
        a = self.make_lead(self.mk_agent)
        c = row_can(self.mk_agent, a)
        self.assertTrue(c["note"] and c["edit"])
        self.assertFalse(c["status"] or c["assign"])
        self.assertFalse(any(row_can(self.mk_agent, self.make_lead(self.mk_leader)).values()))

    def test_row_can_sales_agent_unassigned_lead(self):
        a = self.make_lead(self.mk_agent)
        self.assertFalse(any(row_can(self.sales_agent, a).values()))

    def test_row_can_sales_leader_scope(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent2)
        self.assertFalse(row_can(self.sales_leader, a)["status"])
        self.assertTrue(row_can(self.sales_leader, self.make_lead(self.mk_agent))["status"])

    def test_row_can_admin_and_outsider(self):
        a = self.make_lead(self.mk_agent)
        c = row_can(self.manager, a)
        self.assertTrue(all(v for k, v in c.items() if k != "return"))
        self.assertFalse(c["return"])
        self.assertFalse(any(row_can(self.outsider, a).values()))

    def test_capabilities_owner(self):
        c = capabilities(self.owner)
        self.assertTrue(c["upload"] and c["delete_by_phones_all_projects"] and c["view_hidden"])

    def test_capabilities_manager(self):
        c = capabilities(self.manager)
        self.assertTrue(c["delete_by_phones"])
        self.assertFalse(c["delete_by_phones_all_projects"] or c["upload"])

    def test_capabilities_sales_leader(self):
        c = capabilities(self.sales_leader)
        self.assertTrue(c["assign"])
        self.assertFalse(c["create"] or c["view_hidden"])
        self.assertEqual((c["department"], c["level"]), ("sales", "leader"))

    def test_scope_inactive_assignment_excluded(self):
        a = self.make_lead(self.mk_agent)
        s = self.assign(a, self.sales_agent)
        s.is_active = False
        s.save()
        self.assertEqual(ids(self.scope(self.sales_agent)), set())

    def test_scope_sales_leader_inactive_sales_assignment_is_unassigned(self):
        a = self.make_lead(self.mk_agent)
        s = self.assign(a, self.sales_agent2)
        s.is_active = False
        s.save()
        self.assertEqual(ids(self.scope(self.sales_leader)), {a.uuid})

    def test_scope_hidden_lead_excluded_for_non_admin(self):
        self.make_lead(self.mk_agent, is_hidden=True)
        self.assertEqual(ids(self.scope(self.mk_agent)), set())

    def test_row_can_assigned_sales_agent_edit_status_note(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent)
        c = row_can(self.sales_agent, a)
        self.assertTrue(c["edit"] and c["status"] and c["note"])
        self.assertFalse(c["assign"])

    def test_row_can_marketing_leader_team_scope(self):
        c = row_can(self.mk_leader, self.make_lead(self.mk_agent))
        self.assertTrue(c["edit"] and c["note"])
        self.assertFalse(c["status"] or c["assign"])
        self.assertFalse(any(row_can(self.mk_leader, self.make_lead(self.owner)).values()))

    def test_row_can_sales_leader_other_team_cannot_assign(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_agent2)
        self.assertFalse(row_can(self.sales_leader, a)["assign"])

    def test_row_can_sales_leader_as_assignee_can_return(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.sales_leader)
        self.assertTrue(row_can(self.sales_leader, a)["return"])

    def test_row_can_admin_as_assignee_can_return(self):
        a = self.make_lead(self.mk_agent)
        self.assign(a, self.manager)
        self.assertTrue(row_can(self.manager, a)["return"])
