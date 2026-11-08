from apps.reports.errors import ReportError
from apps.reports.models import ReportField, ReportSection, ReportValue
from apps.reports.services import definition
from apps.reports.tests.base import ReportsTestCase
from apps.reports.services import submissions
from datetime import date
from apps.users.models import User


class DefinitionTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.rt = self.make_type("daily")

    def payload(self):
        out = []
        for s in self.rt.sections.all():
            out.append({"uuid": str(s.uuid), "name": s.name, "order": s.order, "is_active": s.is_active,
                        "fields": [{"uuid": str(f.uuid), "label": f.label, "kind": f.kind,
                                    "required": f.required, "order": f.order, "is_active": f.is_active}
                                   for f in s.fields.all()]})
        return out

    def test_create_from_payload(self):
        rt = self.make_type("daily", sections=[])
        definition.save_definition(rt, [
            {"name": "A", "order": 0, "fields": [
                {"label": "x", "kind": "number", "required": True, "order": 0}]},
            {"name": "B", "order": 1, "is_active": True, "fields": []}])
        self.assertEqual(rt.sections.count(), 2)
        f = ReportField.objects.get(section__report_type=rt)
        self.assertEqual((f.label, f.kind, f.required, f.is_active), ("x", "number", True, True))

    def test_update_rename_reorder(self):
        p = self.payload()
        p[0]["name"] = "Renamed"
        p[0]["fields"][0]["order"] = 5
        p[0]["fields"][0]["label"] = "nn"
        definition.save_definition(self.rt, p)
        s = ReportSection.objects.get(report_type=self.rt)
        self.assertEqual(s.name, "Renamed")
        self.assertEqual(s.fields.count(), 3)
        self.assertEqual(s.fields.get(uuid=p[0]["fields"][0]["uuid"]).order, 5)

    def test_omitted_unused_deleted(self):
        p = self.payload()
        p[0]["fields"].pop()
        definition.save_definition(self.rt, p)
        self.assertEqual(ReportField.objects.filter(section__report_type=self.rt).count(), 2)
        definition.save_definition(self.rt, [])
        self.assertEqual(ReportSection.objects.filter(report_type=self.rt).count(), 0)

    def _use_fields(self):
        u = User.objects.create_user(username="m", password="x", department=self.marketing)
        fid = str(self.rt.sections.first().fields.get(label="n").uuid)
        submissions.save_submission(self.rt, u, date(2026, 11, 8), {fid: 1}, date(2026, 11, 8))
        return fid

    def test_definition_deactivates_used_field(self):
        fid = self._use_fields()
        p = self.payload()
        p[0]["fields"] = [f for f in p[0]["fields"] if f["uuid"] != fid]
        definition.save_definition(self.rt, p)
        self.assertFalse(ReportField.objects.get(uuid=fid).is_active)
        definition.save_definition(self.rt, [])
        self.assertFalse(ReportSection.objects.get(report_type=self.rt).is_active)
        self.assertTrue(ReportValue.objects.exists())

    def test_kind_locked(self):
        fid = self._use_fields()
        p = self.payload()
        for f in p[0]["fields"]:
            if f["uuid"] == fid:
                f["kind"] = "text"
        with self.assertRaises(ReportError) as cm:
            definition.save_definition(self.rt, p)
        self.assertEqual(cm.exception.type, "kind_locked")

    def test_kind_change_without_values(self):
        p = self.payload()
        p[0]["fields"][0]["kind"] = "text"
        definition.save_definition(self.rt, p)
        self.assertEqual(ReportField.objects.get(uuid=p[0]["fields"][0]["uuid"]).kind, "text")

    def test_foreign_uuid_invalid(self):
        other = self.make_type("daily")
        p = self.payload()
        p[0]["fields"][0]["uuid"] = str(ReportField.objects.filter(section__report_type=other).first().uuid)
        with self.assertRaises(ReportError) as cm:
            definition.save_definition(self.rt, p)
        self.assertEqual(cm.exception.type, "invalid")
        p = self.payload()
        p[0]["uuid"] = str(other.sections.first().uuid)
        with self.assertRaises(ReportError) as cm:
            definition.save_definition(self.rt, p)
        self.assertEqual(cm.exception.type, "invalid")
