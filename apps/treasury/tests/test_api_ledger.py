import datetime as dt
import io
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.treasury.models import ImportBatch, ProjectGroup, TreasuryEntry
from apps.treasury.services import importer
from apps.users.tests.base import BaseUserTestCase
from apps.users.tests.user_admin_factories import make_user
from apps.users.types import UserTypes

B = "/api/treasury/"


def csv_file(text, name="s.csv"):
    return SimpleUploadedFile(name, text.encode())


def xlsx_file(rows, name="s.xlsx"):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue())


class TreasuryApiBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.owner = make_user("t_owner", UserTypes.OWNER)
        self.hr = make_user("t_hr", UserTypes.HR)
        self.authenticate_as(self.owner)

    def entry(self, **kw):
        base = dict(direction="out", category="operating", amount="10.00", date="2026-10-01",
                    details="x")
        base.update(kw)
        return self.client.post(B + "entries", base, format="json")


class PermissionTests(TreasuryApiBase):
    def test_non_top_forbidden_everywhere(self):
        rid = uuid.uuid4()
        calls = [
            ("get", "balance"), ("get", "groups/breakdown"), ("get", "entries"), ("post", "entries"),
            ("post", f"entries/{rid}/reverse"), ("get", "groups"), ("post", "groups"),
            ("patch", f"groups/{rid}"), ("delete", f"groups/{rid}"), ("post", "import/preview"),
            ("get", "import"), ("post", "import"), ("post", f"import/{rid}/reverse"),
        ]
        for user in (self.hr, self.agent):
            self.authenticate_as(user)
            for method, path in calls:
                r = getattr(self.client, method)(B + path)
                self.assertEqual(r.status_code, 403, (user.username, method, path))
                self.assertEqual(r.data["type"], "forbidden")

    def test_owner_and_superuser_allowed(self):
        for user in (self.owner, self.superuser):
            self.authenticate_as(user)
            self.assertEqual(self.client.get(B + "balance").status_code, 200)


class BalanceTests(TreasuryApiBase):
    def test_shape_and_month(self):
        self.entry(direction="in", category="income", amount="100")
        self.entry(amount="30.5")
        r = self.client.get(B + "balance?month=2026-10")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {
            "all_time": {"income": "100.00", "outcome": "30.50", "net": "69.50"},
            "month": {"income": "100.00", "outcome": "30.50", "net": "69.50"}})
        r = self.client.get(B + "balance?month=2026-09")
        self.assertEqual(r.data["month"]["income"], "0.00")
        self.assertIsNone(self.client.get(B + "balance").data["month"])

    def test_bad_month(self):
        for m in ("2026-13", "abc", "2026-1"):
            r = self.client.get(B + f"balance?month={m}")
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_breakdown(self):
        g = ProjectGroup.objects.create(name="G")
        self.entry(amount="5", group=str(g.uuid))
        self.entry(amount="7")
        r = self.client.get(B + "groups/breakdown?month=2026-10")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["group"], {"id": str(g.uuid), "name": "G"})
        self.assertEqual(r.data[0]["outcome"], "5.00")
        self.assertIsNone(r.data[-1]["group"])
        self.assertEqual(r.data[-1]["outcome"], "7.00")


class EntryTests(TreasuryApiBase):
    def test_create_ignores_created_by_and_shape(self):
        r = self.entry(created_by=str(self.hr.uuid))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["created_by"]["uuid"], str(self.owner.uuid))
        for k in ("id", "direction", "category", "amount", "date", "details", "group", "advance_id",
                  "import_batch_id", "reverses_id", "reversed_at", "reversal_reason", "created_at"):
            self.assertIn(k, r.data)
        self.assertEqual(r.data["amount"], "10.00")
        self.assertEqual(r.data["date"], "2026-10-01")

    def test_create_invalid(self):
        r = self.entry(amount="-1")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.entry(date="nope")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.entry(category="advance")
        self.assertEqual(r.status_code, 400)
        r = self.entry(group=str(uuid.uuid4()))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_filters_and_pagination(self):
        g = ProjectGroup.objects.create(name="G")
        self.entry(direction="in", category="income", date="2026-09-01")
        self.entry(group=str(g.uuid), date="2026-10-02")
        self.entry(category="other", date="2026-10-03")
        def ids(q):
            r = self.client.get(B + "entries?" + q)
            self.assertEqual(r.status_code, 200)
            return r.data["count"]
        self.assertEqual(ids("direction=in"), 1)
        self.assertEqual(ids("category=other"), 1)
        self.assertEqual(ids("group=none"), 2)
        self.assertEqual(ids(f"group={g.uuid}"), 1)
        self.assertEqual(ids("date_from=2026-10-01"), 2)
        self.assertEqual(ids("date_to=2026-09-30"), 1)
        self.assertEqual(self.client.get(B + "entries?group=zzz").status_code, 400)
        self.assertEqual(self.client.get(B + "entries?date_from=zzz").status_code, 400)
        for i in range(52):
            self.entry()
        r = self.client.get(B + "entries")
        self.assertEqual(r.data["count"], 55)
        self.assertEqual(len(r.data["results"]), 50)
        self.assertEqual(len(self.client.get(B + "entries?page=2").data["results"]), 5)

    def test_reverse(self):
        e = self.entry().data
        r = self.client.post(B + f"entries/{e['id']}/reverse", {"reason": "oops"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["reverses_id"], e["id"])
        r = self.client.post(B + f"entries/{e['id']}/reverse", {"reason": "oops"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "already_reversed"))
        r = self.client.post(B + f"entries/{uuid.uuid4()}/reverse", {"reason": "x"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (404, "not_found"))
        r = self.client.post(B + f"entries/{e['id']}/reverse", {}, format="json")
        self.assertEqual(r.status_code, 400)


class GroupTests(TreasuryApiBase):
    def test_crud(self):
        r = self.client.post(B + "groups", {"name": "A", "project_ids": [str(self.project.uuid)]}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["projects"], [{"id": str(self.project.uuid), "name": "Test Project"}])
        gid = r.data["id"]
        self.assertEqual(len(self.client.get(B + "groups").data), 1)
        r = self.client.patch(B + f"groups/{gid}", {"name": "B", "project_ids": []}, format="json")
        self.assertEqual((r.status_code, r.data["name"], r.data["projects"]), (200, "B", []))
        r = self.client.post(B + "groups", {"name": "b", "project_ids": []}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate"))
        self.assertEqual(self.client.delete(B + f"groups/{gid}").status_code, 204)
        self.assertEqual(self.client.delete(B + f"groups/{gid}").status_code, 404)

    def test_in_use(self):
        g = ProjectGroup.objects.create(name="G")
        self.entry(group=str(g.uuid))
        r = self.client.delete(B + f"groups/{g.uuid}")
        self.assertEqual((r.status_code, r.data["type"]), (400, "in_use"))


class ImportTests(TreasuryApiBase):
    def preview(self, f, **extra):
        return self.client.post(B + "import/preview", {"file": f, **extra}, format="multipart")

    def test_preview_clean(self):
        g = ProjectGroup.objects.create(name="G")
        r = self.preview(csv_file("date,amount,details,category,group\n2026-10-01,5,Rent,,\n"),
                         group=str(g.uuid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["errors"], [])
        self.assertEqual(r.data["rows"], [{"date": "2026-10-01", "amount": "5.00", "details": "Rent",
                                           "category": "operating",
                                           "group": {"id": str(g.uuid), "name": "G"}}])

    def test_preview_errors_and_bad_file(self):
        r = self.preview(csv_file("date,amount,details\nbad,5,Rent\n"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["errors"][0]["field"], "date")
        self.assertEqual(len(r.data["rows"]), 1)
        r = self.preview(csv_file("a,b\n1,2\n"))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_file"))
        r = self.client.post(B + "import/preview", {}, format="multipart")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_preview_xlsx_date_cells(self):
        f = xlsx_file([["date", "amount", "details"], [dt.date(2026, 10, 1), 5, "Rent"]])
        r = self.preview(f)
        self.assertEqual(r.data["rows"][0]["date"], "2026-10-01")

    def test_commit_flow(self):
        g = ProjectGroup.objects.create(name="G")
        rows = self.preview(csv_file("date,amount,details,group\n2026-10-01,5,Rent,G\n")).data["rows"]
        r = self.client.post(B + "import", {"rows": rows}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["row_count"], 1)
        e = TreasuryEntry.objects.get(import_batch_id=r.data["batch_id"])
        self.assertEqual(e.group, g)
        self.assertEqual(e.created_by, self.owner)
        bid = r.data["batch_id"]
        lst = self.client.get(B + "import")
        self.assertEqual(lst.status_code, 200)
        self.assertEqual(lst.data[0]["id"], bid)
        self.assertEqual(lst.data[0]["created_by"]["uuid"], str(self.owner.uuid))
        r = self.client.post(B + f"import/{bid}/reverse", {"reason": "mistake"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["id"], bid)
        self.assertIsNotNone(r.data["reversed_at"])
        r = self.client.post(B + f"import/{bid}/reverse", {"reason": "mistake"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "already_reversed"))
        r = self.client.post(B + f"import/{uuid.uuid4()}/reverse", {"reason": "m"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_commit_group_object_and_default(self):
        g = ProjectGroup.objects.create(name="G")
        rows = [{"date": "2026-10-01", "amount": "5.00", "details": "a", "category": "operating",
                 "group": {"id": str(g.uuid), "name": "G"}},
                {"date": "2026-10-01", "amount": "6.00", "details": "b", "category": "operating",
                 "group": None}]
        r = self.client.post(B + "import", {"rows": rows, "group": str(g.uuid)}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(TreasuryEntry.objects.filter(group=g).count(), 2)

    def test_commit_errors(self):
        rows = [{"date": "bad", "amount": "5", "details": "a", "category": "", "group": None}]
        r = self.client.post(B + "import", {"rows": rows}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "invalid")
        self.assertEqual(r.data["errors"][0]["field"], "date")
        self.assertEqual(TreasuryEntry.objects.count(), 0)
        r = self.client.post(B + "import", {"rows": "x"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.client.post(B + "import", {"rows": [1]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_too_many_rows(self):
        rows = [{"date": "2026-10-01", "amount": "1", "details": "a"}] * (importer.MAX_ROWS + 1)
        r = self.client.post(B + "import", {"rows": rows}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "too_many_rows"))
