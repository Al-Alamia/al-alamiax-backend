import uuid
from datetime import date
from decimal import Decimal

from apps.treasury.models import ProjectGroup, TreasuryEntry
from apps.treasury.services import TreasuryError
from apps.treasury.services import ledger
from apps.users.models import Project
from apps.users.tests.base import BaseUserTestCase

D = Decimal


class LedgerTests(BaseUserTestCase):
    def _in(self, amount="1000", d=date(2026, 10, 15)):
        return ledger.add_entry(self.superuser, "in", "income", amount, d, "Client payment")

    def _out(self, amount, d=date(2026, 10, 15), group=None):
        return ledger.add_entry(self.superuser, "out", "operating", amount, d, "Rent", group=group)

    def assertInvalid(self, *args, **kw):
        with self.assertRaises(TreasuryError) as cm:
            ledger.add_entry(*args, **kw)
        self.assertEqual(cm.exception.type, "invalid")

    def test_balance_all_time_and_month(self):
        self._in()
        self._out("300")
        self._out("200", date(2026, 9, 10))
        self.assertEqual(ledger.balance(None), {"income": D(1000), "outcome": D(500), "net": D(500)})
        self.assertEqual(ledger.balance(date(2026, 10, 1)),
                         {"income": D(1000), "outcome": D(300), "net": D(700)})

    def test_reversal_nets_out(self):
        self._in()
        out = self._out("300")
        self._out("200", date(2026, 9, 10))
        rev = ledger.reverse_entry(self.superuser, out, "mistake")
        self.assertEqual((rev.direction, rev.category, rev.amount), ("in", "operating", D(300)))
        self.assertEqual(rev.reverses, out)
        self.assertEqual(ledger.balance(None), {"income": D(1000), "outcome": D(200), "net": D(800)})

    def test_add_entry_rejects_bad_pairing(self):
        d = date(2026, 10, 15)
        g = ProjectGroup.objects.create(name="G")
        u = self.superuser
        self.assertInvalid(u, "in", "operating", "5", d, "x")
        self.assertInvalid(u, "out", "income", "5", d, "x")
        self.assertInvalid(u, "out", "advance", "5", d, "x")
        self.assertInvalid(u, "in", "advance", "5", d, "x")
        self.assertInvalid(u, "in", "income", "5", d, "x", group=g)
        self.assertInvalid(u, "out", "operating", "5", date(2999, 1, 1), "x")
        self.assertInvalid(u, "out", "operating", "5", None, "x")
        self.assertInvalid(u, "out", "operating", "5", d, "  ")
        self.assertInvalid(u, "out", "operating", "5", d, "x" * 251)
        for bad in ("0", "-1", "1.005", "abc", True, None, "NaN", "10000000000"):
            self.assertInvalid(u, "out", "operating", bad, d, "x")
        self.assertEqual(TreasuryEntry.objects.count(), 0)

    def test_reverse_guards(self):
        u = self.superuser
        e = self._out("10")
        rev = ledger.reverse_entry(u, e, "oops")
        for entry, reason, code in [(e, "again", "already_reversed"), (rev, "r", "is_reversal"),
                                    (self._out("5"), " ", "invalid")]:
            with self.assertRaises(TreasuryError) as cm:
                ledger.reverse_entry(u, entry, reason)
            self.assertEqual(cm.exception.type, code)

    def test_reverse_advance_entry(self):
        from apps.treasury.models import Advance
        adv = Advance.objects.create(user=self.agent, amount=100, installments=1, start_period="2026-11")
        e = TreasuryEntry.objects.create(direction="out", category="advance", amount=100,
                                         date=date(2026, 10, 1), details="Adv", advance=adv)
        with self.assertRaises(TreasuryError) as cm:
            ledger.reverse_entry(self.superuser, e, "r")
        self.assertEqual(cm.exception.type, "advance_entry")
        rev = ledger.reverse_entry(self.superuser, e, "r", allow_advance=True)
        self.assertEqual(rev.advance, adv)
        self.assertEqual(rev.direction, "in")

    def test_reverse_copies_group_and_dates_today(self):
        g = ProjectGroup.objects.create(name="G")
        e = self._out("40", date(2026, 1, 5), group=g)
        rev = ledger.reverse_entry(self.superuser, e, "why")
        e.refresh_from_db()
        self.assertEqual(rev.group, g)
        self.assertEqual(rev.date, date.today())
        self.assertEqual(rev.details, "Reversal: Rent")
        self.assertEqual(rev.created_by, self.superuser)
        self.assertIsNotNone(e.reversed_at)
        self.assertEqual(e.reversal_reason, "why")

    def test_reverse_truncates_details(self):
        e = ledger.add_entry(self.superuser, "out", "other", "1", date(2026, 10, 1), "x" * 250)
        rev = ledger.reverse_entry(self.superuser, e, "r")
        self.assertEqual(len(rev.details), 250)

    def test_breakdown_includes_empty_groups_and_ungrouped(self):
        a = ProjectGroup.objects.create(name="A")
        b = ProjectGroup.objects.create(name="B")
        ea = self._out("400", group=a)
        self._out("100")
        rows = ledger.group_breakdown(None)
        self.assertEqual([(r["group"], r["outcome"]) for r in rows], [(a, D(400)), (b, D(0)), (None, D(100))])
        ledger.reverse_entry(self.superuser, ea, "r")
        rows = ledger.group_breakdown(None)
        self.assertEqual([(r["group"], r["outcome"]) for r in rows], [(a, D(0)), (b, D(0)), (None, D(100))])
        rows = ledger.group_breakdown(date(2020, 1, 1))
        self.assertEqual([r["outcome"] for r in rows], [D(0), D(0), D(0)])

    def test_group_crud(self):
        p2 = Project.objects.create(name="P2")
        g = ledger.create_group(self.superuser, "Ops", [self.project.pk, p2.pk])
        self.assertEqual(g.created_by, self.superuser)
        self.assertEqual(set(g.projects.all()), {self.project, p2})
        for name in ("ops", "OPS", ""):
            with self.assertRaises(TreasuryError):
                ledger.create_group(self.superuser, name, [])
        with self.assertRaises(TreasuryError) as cm:
            ledger.create_group(self.superuser, "Bad", ["not-a-uuid"])
        self.assertEqual(cm.exception.type, "invalid")
        with self.assertRaises(TreasuryError):
            ledger.create_group(self.superuser, "Bad2", [str(uuid.uuid4())])
        other = ledger.create_group(self.superuser, "Other", [])
        with self.assertRaises(TreasuryError) as cm:
            ledger.update_group(other, name="OPS")
        self.assertEqual(cm.exception.type, "duplicate")
        g = ledger.update_group(g, name="OPS", project_ids=[p2.pk])  # own name, case change ok
        self.assertEqual(g.name, "OPS")
        self.assertEqual(list(g.projects.all()), [p2])
        g = ledger.update_group(g, name="Renamed")
        self.assertEqual(list(g.projects.all()), [p2])
        self._out("5", group=g)
        with self.assertRaises(TreasuryError) as cm:
            ledger.delete_group(g)
        self.assertEqual(cm.exception.type, "in_use")
        ledger.delete_group(other)
        self.assertFalse(ProjectGroup.objects.filter(pk=other.pk).exists())
