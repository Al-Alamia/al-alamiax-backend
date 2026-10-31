import io
from datetime import date, datetime
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.treasury.models import ImportBatch, ProjectGroup, TreasuryEntry
from apps.treasury.services import TreasuryError, importer, ledger
from apps.users.tests.base import BaseUserTestCase

HEAD = ["Date", "Amount", "Details", "Category", "Group"]


def xlsx(rows, name="s.xlsx"):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue())


def csv(text, name="s.csv"):
    return SimpleUploadedFile(name, text if isinstance(text, bytes) else text.encode())


def row(**kw):
    base = {"date": "2026-10-01", "amount": "100", "details": "Rent", "category": "", "group": ""}
    base.update(kw)
    return base


class ImporterTests(BaseUserTestCase):
    def assertCode(self, code, fn, *a):
        with self.assertRaises(TreasuryError) as cm:
            fn(*a)
        self.assertEqual(cm.exception.type, code)
        return cm.exception

    def test_parse_xlsx_header_case_and_blank_rows(self):
        f = xlsx([["DATE", "Amount", "DETAILS", "Category", "group"],
                  [datetime(2026, 10, 1), 100, "Rent", None, None],
                  [None, None, None, None, None],
                  ["2026-10-02", "50.5", "Fuel", "operating", "G"]])
        rows = importer.parse_sheet(f)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["details"], "Rent")
        self.assertIsInstance(rows[0]["date"], (date, datetime))
        self.assertEqual(rows[1], {"date": "2026-10-02", "amount": "50.5", "details": "Fuel",
                                   "category": "operating", "group": "G"})

    def test_parse_csv_with_bom(self):
        rows = importer.parse_sheet(csv(b"\xef\xbb\xbfDate,Amount,Details\n2026-10-01,100,Rent\n"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], "100")

    def test_parse_rejects(self):
        self.assertCode("invalid_file", importer.parse_sheet, csv("a", "x.txt"))
        body = "date,amount,details\n" + "2026-10-01,1,x\n" * 501
        self.assertCode("too_many_rows", importer.parse_sheet, csv(body))
        self.assertCode("invalid_file", importer.parse_sheet, csv("date,details\n2026-10-01,x\n"))

    def test_validate_rows_errors(self):
        rows = [row(date="nope"), row(date="2999-01-01"), row(amount="0"), row(details=" "),
                row(category="income"), row(category="advance"), row(group="Nope")]
        clean, errors = importer.validate_rows(rows, None)
        self.assertEqual(clean, [])
        self.assertEqual([(e["row"], e["field"]) for e in errors],
                         [(1, "date"), (2, "date"), (3, "amount"), (4, "details"),
                          (5, "category"), (6, "category"), (7, "group")])

    def test_validate_defaults(self):
        g = ProjectGroup.objects.create(name="Alpha", created_by=self.superuser)
        d = ProjectGroup.objects.create(name="Default", created_by=self.superuser)
        clean, errors = importer.validate_rows([row(), row(group="aLPHA", amount=12.5)], d)
        self.assertEqual(errors, [])
        self.assertEqual((clean[0]["category"], clean[0]["group"]), ("operating", d))
        self.assertEqual(clean[1]["group"], g)
        self.assertEqual(clean[1]["amount"], Decimal("12.5"))
        self.assertEqual(clean[0]["date"], date(2026, 10, 1))

    def test_import_all_or_nothing(self):
        e = self.assertCode("invalid", importer.import_rows, self.superuser,
                            [row(), row(), row(amount="x")], None)
        self.assertEqual(e.errors[0]["row"], 3)
        self.assertEqual(ImportBatch.objects.count(), 0)
        self.assertEqual(TreasuryEntry.objects.count(), 0)
        b = importer.import_rows(self.superuser, [row(), row(), row()], None)
        self.assertEqual(b.row_count, 3)
        qs = TreasuryEntry.objects.filter(import_batch=b)
        self.assertEqual(qs.count(), 3)
        self.assertEqual({x.direction for x in qs}, {"out"})

    def test_reverse_batch(self):
        b = importer.import_rows(self.superuser, [row(), row()], None)
        importer.reverse_batch(self.superuser, b, "oops")
        b.refresh_from_db()
        self.assertIsNotNone(b.reversed_at)
        self.assertEqual(b.reversed_by, self.superuser)
        self.assertEqual(b.reversal_reason, "oops")
        self.assertEqual(TreasuryEntry.objects.filter(reverses__isnull=False).count(), 2)
        self.assertCode("already_reversed", importer.reverse_batch, self.superuser, b, "again")

    def test_reverse_batch_partially_reversed(self):
        b = importer.import_rows(self.superuser, [row(), row()], None)
        ledger.reverse_entry(self.superuser, TreasuryEntry.objects.filter(import_batch=b).first(), "x")
        self.assertCode("partially_reversed", importer.reverse_batch, self.superuser, b, "r")
        b.refresh_from_db()
        self.assertIsNone(b.reversed_at)
        self.assertEqual(TreasuryEntry.objects.filter(reverses__isnull=False).count(), 1)
