from apps.users.models import LeadUpdate
from apps.users.tests.lead_fixtures import LeadPipelineTestCase

URL = "/api/users/leads"


class LeadActionTests(LeadPipelineTestCase):
    def post(self, user, lead, action, data):
        self.client.force_authenticate(user)
        return self.client.post(f"{URL}/{lead.uuid}/{action}", data, format="json")

    def test_status_change_logs_from_to(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent)
        response = self.post(
            self.sales_agent, lead, "status", {"status": "contacted", "call_status": "called"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "contacted")
        pairs = set(
            LeadUpdate.objects.filter(lead=lead, type__in=["status", "call_status"]).values_list(
                "from_value", "to_value"
            )
        )
        self.assertEqual(pairs, {("new", "contacted"), ("pending", "called")})

    def test_status_unchanged_logs_nothing(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent)
        before = LeadUpdate.objects.filter(lead=lead).count()
        response = self.post(self.sales_agent, lead, "status", {"status": "new"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LeadUpdate.objects.filter(lead=lead).count(), before)

    def test_status_forbidden_for_marketing(self):
        lead = self.make_lead(self.mk_agent)
        response = self.post(self.mk_agent, lead, "status", {"status": "contacted"})
        self.assertEqual(response.status_code, 403)

    def test_status_invalid_choice(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent)
        response = self.post(self.sales_agent, lead, "status", {"status": "bogus"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("message", response.data)

    def test_note_by_marketing_creator(self):
        lead = self.make_lead(self.mk_agent)
        response = self.post(self.mk_agent, lead, "notes", {"note": "hello"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["type"], "note")
        self.assertEqual(response.data["note"], "hello")

    def test_note_blank_400(self):
        lead = self.make_lead(self.mk_agent)
        response = self.post(self.mk_agent, lead, "notes", {"note": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn("message", response.data)

    def test_updates_newest_first(self):
        self.client.force_authenticate(self.mk_agent)
        created = self.client.post(URL, {"name": "N", "phone": "0100000009"}, format="json")
        self.assertEqual(created.status_code, 201)
        uuid = created.data["uuid"]
        self.client.post(f"{URL}/{uuid}/notes", {"note": "x"}, format="json")
        response = self.client.get(f"{URL}/{uuid}/updates")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["type"], "note")
        self.assertEqual(response.data["count"], 2)
