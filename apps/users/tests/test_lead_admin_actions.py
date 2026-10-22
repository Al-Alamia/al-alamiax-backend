from uuid import uuid4

from apps.users.models import Lead, LeadUpdate, Project
from apps.users.tests.lead_fixtures import LeadPipelineTestCase
from utils.phones import normalize_sa_phone

URL = "/api/users/leads"
DELETE_URL = f"{URL}/delete-by-phones"


class NormalizePhoneTests(LeadPipelineTestCase):
    def test_normalize_variants(self):
        raw = ["+966 5 1234 5678", "966512345678", "0512345678", "512345678", "12345"]
        self.assertEqual(
            [normalize_sa_phone(p) for p in raw], ["966512345678"] * 4 + [None]
        )


class HideTests(LeadPipelineTestCase):
    def uuids(self, response):
        return {str(row["uuid"]) for row in response.data["results"]}

    def test_hide_and_unhide(self):
        lead = self.make_lead(self.mk_agent)
        self.client.force_authenticate(self.manager)
        response = self.client.post(f"{URL}/{lead.uuid}/hide")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_hidden"])
        self.assertTrue(LeadUpdate.objects.filter(lead=lead, type="hidden").exists())
        self.assertNotIn(str(lead.uuid), self.uuids(self.client.get(URL)))
        self.assertIn(str(lead.uuid), self.uuids(self.client.get(f"{URL}?hidden=true")))

        self.assertEqual(self.client.post(f"{URL}/{lead.uuid}/hide").status_code, 400)
        response = self.client.post(f"{URL}/{lead.uuid}/unhide")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_hidden"])
        self.assertTrue(LeadUpdate.objects.filter(lead=lead, type="unhidden").exists())
        self.assertIn(str(lead.uuid), self.uuids(self.client.get(URL)))

    def test_hide_and_unhide_already_state_400(self):
        lead = self.make_lead(self.mk_agent)
        self.client.force_authenticate(self.manager)
        response = self.client.post(f"{URL}/{lead.uuid}/unhide")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Lead is not hidden")
        self.client.post(f"{URL}/{lead.uuid}/hide")
        response = self.client.post(f"{URL}/{lead.uuid}/hide")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Lead is already hidden")

    def test_hide_forbidden_for_leader(self):
        lead = self.make_lead(self.mk_agent)
        self.client.force_authenticate(self.mk_leader)
        self.assertEqual(self.client.post(f"{URL}/{lead.uuid}/hide").status_code, 403)
        lead.refresh_from_db()
        self.assertFalse(lead.is_hidden)

    def test_hide_missing_404(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(f"{URL}/{uuid4()}/hide").status_code, 404)


class DeleteByPhonesTests(LeadPipelineTestCase):
    def delete(self, user, payload):
        self.client.force_authenticate(user)
        return self.client.post(DELETE_URL, payload, format="json")

    def test_delete_by_phones_dedupes(self):
        self.make_lead(self.mk_agent, phone="966512345678")
        self.make_lead(self.mk_leader, phone="0512345678")
        payload = {
            "phones": ["966512345678", "+966 5 1234 5678", "0512345678", "512345678", "bad"],
            "project": str(self.project.uuid),
        }
        response = self.delete(self.manager, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"deleted": 2})
        self.assertEqual(Lead.objects.count(), 0)

    def test_delete_includes_hidden_and_plus_variant(self):
        self.make_lead(self.mk_agent, phone="+966512345678", is_hidden=True)
        response = self.delete(
            self.manager, {"phones": ["0512345678"], "project": str(self.project.uuid)}
        )
        self.assertEqual(response.data, {"deleted": 1})

    def test_delete_by_phones_project_required_for_manager(self):
        self.make_lead(self.mk_agent, phone="966512345678")
        response = self.delete(self.manager, {"phones": ["0512345678"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Project is required")
        self.assertEqual(Lead.objects.count(), 1)

    def test_delete_by_phones_owner_all_projects(self):
        other = Project.objects.create(name="Other")
        self.make_lead(self.mk_agent, phone="966512345678")
        self.make_lead(self.mk_agent, phone="966512345679", project=other)
        response = self.delete(self.owner, {"phones": ["0512345678", "0512345679"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"deleted": 2})

    def test_delete_by_phones_project_filter(self):
        other = Project.objects.create(name="Other")
        self.make_lead(self.mk_agent, phone="966512345678")
        survivor = self.make_lead(self.mk_leader, phone="966512345678", project=other)
        response = self.delete(
            self.manager, {"phones": ["966512345678"], "project": str(self.project.uuid)}
        )
        self.assertEqual(response.data, {"deleted": 1})
        self.assertEqual(list(Lead.objects.all()), [survivor])

    def test_delete_by_phones_forbidden_for_leader(self):
        self.make_lead(self.mk_agent, phone="966512345678")
        response = self.delete(self.mk_leader, {"phones": ["966512345678"]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Lead.objects.count(), 1)

    def test_delete_by_phones_validation(self):
        for payload in (
            {"phones": "966512345678", "project": str(self.project.uuid)},
            {"phones": [1], "project": str(self.project.uuid)},
            {"phones": ["966512345678"], "project": "nope"},
        ):
            self.assertEqual(self.delete(self.manager, payload).status_code, 400, payload)
        response = self.delete(self.manager, {"phones": ["bad"], "project": str(self.project.uuid)})
        self.assertEqual(response.data, {"deleted": 0})
