from uuid import uuid4

from apps.users.models import LeadAssignment, LeadUpdate
from apps.users.tests.lead_fixtures import LeadPipelineTestCase

URL = "/api/users/leads"


class LeadAssignTests(LeadPipelineTestCase):
    def post_assign(self, user, leads, agent, kind="sales"):
        self.client.force_authenticate(user)
        payload = {"leads": [str(l.uuid) if hasattr(l, "uuid") else l for l in leads],
                   "agent": str(agent.uuid) if hasattr(agent, "uuid") else agent, "kind": kind}
        return self.client.post(f"{URL}/assign", payload, format="json")

    def active(self, lead, kind="sales"):
        return LeadAssignment.objects.filter(lead=lead, kind=kind, is_active=True)

    def test_assign_bulk_sets_status(self):
        leads = [self.make_lead(self.mk_agent), self.make_lead(self.mk_agent)]
        response = self.post_assign(self.manager, leads, self.sales_agent)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"assigned": 2})
        for lead in leads:
            lead.refresh_from_db()
            self.assertEqual(lead.status, "assigned")
        updates = LeadUpdate.objects.filter(type="assigned", to_value="sales_agent", note="sales")
        self.assertEqual(updates.count(), 2)

    def test_assign_cs_keeps_status(self):
        lead = self.make_lead(self.mk_agent)
        response = self.post_assign(self.manager, [lead], self.sales_agent, kind="cs")
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.status, "new")
        self.assertEqual(self.active(lead, "cs").count(), 1)

    def test_reassign_deactivates_previous(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent)
        response = self.post_assign(self.manager, [lead], self.sales_agent2)
        self.assertEqual(response.status_code, 200)
        active = self.active(lead)
        self.assertEqual(active.count(), 1)
        self.assertEqual(active.first().agent, self.sales_agent2)

    def test_assign_non_sales_agent_400(self):
        lead = self.make_lead(self.mk_agent)
        response = self.post_assign(self.manager, [lead], self.mk_leader)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"message": "Agent is not in Sales"})

    def test_leader_outside_team_400(self):
        lead = self.make_lead(self.mk_agent)
        response = self.post_assign(self.sales_leader, [lead], self.sales_agent2)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"message": "Agent is not in your team"})

    def test_assign_atomic(self):
        first = self.make_lead(self.mk_agent)
        hidden = self.make_lead(self.mk_agent, is_hidden=True)
        response = self.post_assign(self.manager, [first, hidden], self.sales_agent)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {"message": "Lead not found"})
        self.assertFalse(LeadAssignment.objects.filter(lead=first).exists())

    def test_assign_forbidden_for_agent(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent)
        response = self.post_assign(self.sales_agent, [lead], self.sales_agent2)
        self.assertEqual(response.status_code, 403)

    def test_assign_malformed_400(self):
        lead = self.make_lead(self.mk_agent)
        self.client.force_authenticate(self.manager)
        bad = [
            {"leads": [], "agent": str(self.sales_agent.uuid), "kind": "sales"},
            {"leads": "x", "agent": str(self.sales_agent.uuid), "kind": "sales"},
            {"leads": ["nope"], "agent": str(self.sales_agent.uuid), "kind": "sales"},
            {"leads": [str(lead.uuid)], "agent": "nope", "kind": "sales"},
            {"leads": [str(lead.uuid)], "agent": str(uuid4()), "kind": "sales"},
            {"leads": [str(lead.uuid)], "agent": str(self.sales_agent.uuid), "kind": "x"},
            {"leads": [str(lead.uuid)]},
        ]
        for payload in bad:
            response = self.client.post(f"{URL}/assign", payload, format="json")
            self.assertEqual(response.status_code, 400, payload)
            self.assertIn("message", response.data)

    def test_assignable_agents_leader_scope(self):
        self.client.force_authenticate(self.sales_leader)
        response = self.client.get(f"{URL}/assignable-agents?kind=sales")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({a["username"] for a in response.data}, {"sales_agent", "sales_leader"})

    def test_assign_inactive_agent_400(self):
        lead = self.make_lead(self.mk_agent)
        self.sales_agent2.is_active = False
        self.sales_agent2.save()
        response = self.post_assign(self.manager, [lead], self.sales_agent2)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LeadAssignment.objects.filter(lead=lead).exists())

    def test_assignable_agents_excludes_inactive(self):
        self.sales_agent2.is_active = False
        self.sales_agent2.save()
        self.client.force_authenticate(self.manager)
        names = {a["username"] for a in self.client.get(f"{URL}/assignable-agents").data}
        self.assertNotIn("sales_agent2", names)
        self.assertIn("sales_agent", names)

    def test_assign_concurrent_integrity_error_400(self):
        from django.db import IntegrityError
        from unittest import mock

        lead = self.make_lead(self.mk_agent)
        with mock.patch(
            "apps.users.services.leads.LeadAssignment.objects.create", side_effect=IntegrityError
        ):
            response = self.post_assign(self.manager, [lead], self.sales_agent)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"message": "Lead was assigned concurrently, retry"})

    def test_assignable_agents_admin_all_sales(self):
        self.client.force_authenticate(self.manager)
        response = self.client.get(f"{URL}/assignable-agents")
        names = {a["username"] for a in response.data}
        self.assertTrue({"sales_agent", "sales_agent2", "sales_leader"} <= names)
        self.assertNotIn("mk_agent", names)

    def test_assignable_agents_forbidden_for_agent(self):
        self.client.force_authenticate(self.sales_agent)
        self.assertEqual(self.client.get(f"{URL}/assignable-agents").status_code, 403)

    def test_assign_non_object_body_400(self):
        self.client.force_authenticate(self.manager)
        for body in ([], "x", None):
            response = self.client.post(f"{URL}/assign", body, format="json")
            self.assertEqual(response.status_code, 400, body)
            self.assertIn("message", response.data)

    def test_status_non_object_body_400(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent)
        self.client.force_authenticate(self.sales_agent)
        for action in ("status", "notes"):
            response = self.client.post(f"{URL}/{lead.uuid}/{action}", [], format="json")
            self.assertEqual(response.status_code, 400, action)
            self.assertIn("message", response.data)

    def test_assign_ignores_hidden_query_param(self):
        hidden = self.make_lead(self.mk_agent, is_hidden=True)
        response = self.post_assign_qs(self.manager, [hidden], self.sales_agent, "?hidden=true")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(LeadAssignment.objects.filter(lead=hidden).exists())

    def test_assign_ignores_filter_query_params(self):
        lead = self.make_lead(self.mk_agent)
        response = self.post_assign_qs(self.manager, [lead], self.sales_agent, "?status=interested")
        self.assertEqual(response.status_code, 200)

    def test_leader_assigns_to_team_member_and_self(self):
        lead = self.make_lead(self.mk_agent)
        self.assertEqual(self.post_assign(self.sales_leader, [lead], self.sales_agent).status_code, 200)
        self.assertEqual(self.post_assign(self.sales_leader, [lead], self.sales_leader).status_code, 200)
        self.assertEqual(self.active(lead).get().agent, self.sales_leader)

    def post_assign_qs(self, user, leads, agent, qs):
        self.client.force_authenticate(user)
        payload = {"leads": [str(l.uuid) for l in leads], "agent": str(agent.uuid), "kind": "sales"}
        return self.client.post(f"{URL}/assign{qs}", payload, format="json")
