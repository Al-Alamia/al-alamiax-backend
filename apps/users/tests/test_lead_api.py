import base64
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.users.models import Lead, LeadUpdate
from apps.users.tests.lead_fixtures import LeadPipelineTestCase

URL = "/api/users/leads"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class LeadApiTests(LeadPipelineTestCase):
    def get(self, user, path="", **params):
        self.client.force_authenticate(user)
        return self.client.get(f"{URL}{path}", params)

    def test_list_scoped_and_paginated(self):
        for _ in range(16):
            self.make_lead(self.mk_agent)
        self.make_lead(self.mk_leader)
        response = self.get(self.mk_agent)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 16)
        self.assertEqual(len(response.data["results"]), 15)
        keys = {"uuid", "name", "phone", "status", "call_status", "sales_agent", "cs_agent",
                "return_days_left", "can", "created_by", "project_name"}
        self.assertTrue(keys <= set(response.data["results"][0]))
        self.assertIsNone(response.data["results"][0]["stock_market"])

    def test_list_filters(self):
        interested = self.make_lead(self.mk_agent, status="interested", phone="0111111111")
        assigned = self.make_lead(self.mk_agent)
        self.assign(assigned, self.sales_agent)
        returned = self.make_lead(self.mk_agent, return_count=1)

        def uuids(**params):
            return {r["uuid"] for r in self.get(self.owner, **params).data["results"]}

        self.assertEqual(uuids(status="interested"), {str(interested.uuid)})
        self.assertEqual(uuids(search="1111111"), {str(interested.uuid)})
        self.assertEqual(uuids(unassigned="true"), {str(interested.uuid), str(returned.uuid)})
        self.assertEqual(uuids(returned="true"), {str(returned.uuid)})
        self.assertEqual(uuids(assigned_to=str(self.sales_agent.uuid)), {str(assigned.uuid)})

    def test_list_outsider_403(self):
        response = self.get(self.outsider)
        self.assertEqual(response.status_code, 403)
        self.assertIn("message", response.data)

    def test_create_sets_creator_and_logs(self):
        self.client.force_authenticate(self.mk_agent)
        response = self.client.post(URL, {"name": "N", "phone": "0100000001"}, format="json")
        self.assertEqual(response.status_code, 201)
        lead = Lead.objects.get(uuid=response.data["uuid"])
        self.assertEqual(lead.user, self.mk_agent)
        self.assertEqual(lead.project, self.project)
        self.assertEqual(LeadUpdate.objects.filter(lead=lead, type="created").count(), 1)

    def test_create_duplicate_phone_400(self):
        self.make_lead(self.mk_agent, phone="0100000002")
        self.client.force_authenticate(self.mk_agent)
        response = self.client.post(URL, {"name": "N", "phone": "0100000002"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("message", response.data)

    def test_create_forbidden_for_sales_agent(self):
        self.client.force_authenticate(self.sales_agent)
        response = self.client.post(URL, {"name": "N", "phone": "0100000003"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("message", response.data)

    def test_create_with_screenshots(self):
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            self.client.force_authenticate(self.mk_agent)
            files = [SimpleUploadedFile(n, PNG, "image/png") for n in ("a.png", "b.png")]
            response = self.client.post(
                URL, {"name": "N", "phone": "0100000004", "screenshots": files}, format="multipart"
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(len(response.data["screenshots"]), 2)

    def test_detail_out_of_scope_404(self):
        lead = self.make_lead(self.mk_leader)
        response = self.get(self.mk_agent, f"/{lead.uuid}")
        self.assertEqual(response.status_code, 404)
        self.assertIn("message", response.data)

    def test_detail_has_extras(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent)
        data = self.get(self.owner, f"/{lead.uuid}").data
        self.assertEqual(len(data["assignments"]), 1)
        self.assertEqual(data["sales_agent"]["username"], "sales_agent")
        self.assertEqual(data["returns"], [])

    def test_patch_logs_edited(self):
        lead = self.make_lead(self.mk_agent)
        self.client.force_authenticate(self.mk_agent)
        response = self.client.patch(f"{URL}/{lead.uuid}", {"name": "X"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "X")
        update = LeadUpdate.objects.get(lead=lead, type="edited")
        self.assertIn("name", update.note)

    def test_delete_admin_only(self):
        lead = self.make_lead(self.mk_agent)
        self.client.force_authenticate(self.mk_agent)
        response = self.client.delete(f"{URL}/{lead.uuid}")
        self.assertEqual(response.status_code, 403)
        self.client.force_authenticate(self.manager)
        response = self.client.delete(f"{URL}/{lead.uuid}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Lead.objects.filter(pk=lead.pk).exists())

    def test_me_shapes(self):
        keys = {"create", "assign", "view_hidden", "delete_by_phones",
                "delete_by_phones_all_projects", "upload", "department", "level"}
        self.assertEqual(set(self.get(self.owner, "/me").data), keys)
        response = self.get(self.outsider, "/me")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["create"])

    def test_stats(self):
        self.make_lead(self.mk_agent, status="interested")
        self.make_lead(self.mk_agent, return_count=1)
        self.make_lead(self.mk_agent)
        self.make_lead(self.mk_agent, status="not_interested")
        self.assertEqual(
            self.get(self.owner, "/stats").data,
            {"total": 4, "active": 3, "returned": 1, "interested": 1},
        )
