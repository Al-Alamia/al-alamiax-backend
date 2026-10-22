from apps.users.models import LeadAssignment, LeadReturn, LeadUpdate
from apps.users.tests.lead_fixtures import LeadPipelineTestCase

URL = "/api/users/leads"


class LeadReturnTests(LeadPipelineTestCase):
    def do_return(self, user, lead, reason="not interested"):
        self.client.force_authenticate(user)
        return self.client.post(f"{URL}/{lead.uuid}/return", {"reason": reason}, format="json")

    def sales_lead(self, **kwargs):
        lead = self.make_lead(self.mk_agent, status="assigned")
        assignment = self.assign(lead, self.sales_agent, **kwargs)
        return lead, assignment

    def test_return_effects(self):
        lead, assignment = self.sales_lead()
        response = self.do_return(self.sales_agent, lead, "wrong number")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "new")
        self.assertEqual(response.data["return_count"], 1)
        lead.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(lead.status, "new")
        self.assertEqual(lead.return_count, 1)
        self.assertFalse(assignment.is_active)
        record = LeadReturn.objects.get(lead=lead)
        self.assertEqual(record.assignment, assignment)
        self.assertEqual(record.returned_by, self.sales_agent)
        self.assertEqual(record.reason, "wrong number")
        update = LeadUpdate.objects.get(lead=lead, type="returned")
        self.assertEqual(update.note, "wrong number")
        self.assertEqual(update.by, self.sales_agent)

    def test_return_by_cs_agent_400(self):
        lead, _ = self.sales_lead()
        self.assign(lead, self.sales_agent2, kind="cs")
        response = self.do_return(self.sales_agent2, lead)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["message"], "Only the assigned sales agent can return this lead"
        )

    def test_return_twice_400(self):
        lead, _ = self.sales_lead()
        self.assertEqual(self.do_return(self.sales_agent, lead).status_code, 200)
        self.assign(lead, self.sales_agent)
        response = self.do_return(self.sales_agent, lead)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Lead already returned once")
        self.assertEqual(LeadReturn.objects.filter(lead=lead).count(), 1)

    def test_return_refused_after_reassign_when_already_returned(self):
        lead, _ = self.sales_lead()
        self.assertEqual(self.do_return(self.sales_agent, lead).status_code, 200)
        self.assign(lead, self.sales_agent2)
        response = self.do_return(self.sales_agent2, lead)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Lead already returned once")

    def test_return_window_closed_400(self):
        lead, _ = self.sales_lead(days_ago=10)
        response = self.do_return(self.sales_agent, lead)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Return window closed (5 working days)")
        self.assertTrue(LeadAssignment.objects.get(lead=lead).is_active)

    def test_return_blank_reason_400(self):
        lead, _ = self.sales_lead()
        response = self.do_return(self.sales_agent, lead, "   ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Reason is required")
        lead.refresh_from_db()
        self.assertEqual(lead.return_count, 0)

    def test_return_non_assignee_in_scope_400(self):
        lead, _ = self.sales_lead()
        response = self.do_return(self.sales_leader, lead)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["message"], "Only the assigned sales agent can return this lead"
        )

    def test_return_out_of_scope_404(self):
        lead, _ = self.sales_lead()
        self.assertEqual(self.do_return(self.sales_agent2, lead).status_code, 404)

    def test_detail_can_return_flag(self):
        lead, _ = self.sales_lead()
        self.client.force_authenticate(self.sales_agent)
        response = self.client.get(f"{URL}/{lead.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.data["can"]["return"], True)
        self.assertEqual(response.data["return_days_left"], 5)
