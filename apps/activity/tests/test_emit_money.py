from datetime import date
from decimal import Decimal

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.periods import period_key_for
from apps.activity.models import ActivityEvent
from apps.monthly_basic import services as mb
from apps.payroll_config import services as pc
from apps.payroll_config.tests.factories import make_basic, make_rates
from apps.salaries import services as sal
from apps.salaries.tests.factories import KEY as SKEY, MONTH, give_basic, make_lead_on, window
from apps.subscriptions.tests.factories import marketing_dept
from apps.teams.tests.factories import make_plan, make_version
from apps.teams.types import PlanKind
from apps.treasury.models import ProjectGroup
from apps.treasury.services import advances, importer, ledger
from apps.treasury.tests.test_importer import row
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

KEY = "2026-10"
TODAY = date(2026, 10, 26)
D = Decimal


class EventAssertions:
    def ev(self, verb, actor, subject, area, n=1):
        qs = ActivityEvent.objects.filter(verb=verb)
        self.assertEqual(qs.count(), n, verb)
        e = qs.latest("created_at")
        self.assertEqual((e.actor, e.subject, e.area), (actor, subject, area), verb)
        return e


class MonthlyBasicEventTests(EventAssertions, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR,
                                           department=self.department)
        self.owner = User.objects.create_user(username="own", password="x", role=UserTypes.OWNER)
        make_basic(self.agent, date(2026, 10, 1), 3000)

    def test_lifecycle(self):
        mb.update_inputs(self.hr, self.agent, KEY, {"kpi": "200"}, today=TODAY)
        e = self.ev("basic.inputs_updated", self.hr, self.agent, "payroll")
        self.assertEqual((e.target_label, e.data["fields"]), (KEY, ["kpi"]))
        mb.update_inputs(self.hr, self.agent, KEY, {"kpi": "200"}, today=TODAY)  # no-op
        self.assertEqual(ActivityEvent.objects.filter(verb="basic.inputs_updated").count(), 1)

        rec = mb.give(self.hr, self.agent, KEY, today=TODAY)
        e = self.ev("basic.given", self.hr, self.agent, "payroll")
        self.assertEqual(e.data["net"], f"{rec.net:.2f}")
        sal.give(self.hr, self.agent, KEY, today=TODAY)

        mb.close_period(self.hr, KEY, today=TODAY)
        self.ev("basic.period_closed", self.hr, None, "payroll")
        mb.reopen_period(self.owner, KEY, "fix")
        e = self.ev("basic.period_reopened", self.owner, None, "payroll")
        self.assertEqual(e.data["reason"], "fix")

        sal.ungive(self.hr, self.agent, KEY)
        self.ev("salary.ungiven", self.hr, self.agent, "payroll")
        mb.ungive(self.hr, self.agent, KEY)
        self.ev("basic.ungiven", self.hr, self.agent, "payroll")


class SalaryEventTests(EventAssertions, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.start, self.end = window()
        M = marketing_dept()
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR, department=M)
        self.agent = User.objects.create_user(username="mk", password="x", role=UserTypes.AGENT,
                                              department=M)
        make_basic(self.agent, MONTH, 3000)
        give_basic(self.agent, 2900)
        make_version(make_plan(PlanKind.PERSONAL, department=M), MONTH,
                     [{"min_value": 1, "kind": "unit", "value": 10}])
        make_lead_on(self.agent, self.start)
        self.part = sal.compute(self.agent, SKEY)["parts"][0]["key"]

    def test_override_and_give(self):
        sal.set_override(self.hr, self.agent, SKEY, self.part, "5", "why", today=self.end)
        e = self.ev("salary.override_set", self.hr, self.agent, "payroll")
        self.assertEqual((e.data["value"], e.data["reason"]), ("5.00", "why"))
        sal.clear_override(self.hr, self.agent, SKEY, self.part, today=self.end)
        self.ev("salary.override_cleared", self.hr, self.agent, "payroll")
        sal.clear_override(self.hr, self.agent, SKEY, self.part, today=self.end)  # no-op
        self.ev("salary.override_cleared", self.hr, self.agent, "payroll")

        s = sal.give(self.hr, self.agent, SKEY, today=self.end)
        e = self.ev("salary.given", self.hr, self.agent, "payroll")
        self.assertEqual(e.data["total"], f"{s.total:.2f}")
        sal.ungive(self.hr, self.agent, SKEY)
        self.ev("salary.ungiven", self.hr, self.agent, "payroll")

    def test_give_all_emits_one_summary(self):
        sal.give_all(self.hr, SKEY, today=self.end)
        e = self.ev("salary.given_all", self.hr, None, "payroll")
        self.assertEqual(e.data["count"], 1)
        self.ev("salary.given", self.hr, self.agent, "payroll")
        sal.give_all(self.hr, SKEY, today=self.end)  # nothing left: no event
        self.ev("salary.given_all", self.hr, None, "payroll")


class PayrollConfigEventTests(EventAssertions, BaseUserTestCase):
    today = date(2026, 11, 15)

    def test_config_events(self):
        m = date(2026, 11, 1)
        pc.set_basic(self.agent, m, "100", "n", self.superuser, today=self.today)
        e = self.ev("basic_salary.set", self.superuser, self.agent, "payroll")
        self.assertEqual(e.data["amount"], "100.00")
        pc.set_basic(self.agent, m, "100", "n", self.superuser, today=self.today)  # no-op
        self.ev("basic_salary.set", self.superuser, self.agent, "payroll")

        pc.set_rate(m, "SAR", "12.5", self.superuser)
        self.ev("rate.set", self.superuser, None, "payroll")
        pc.set_rate(m, "SAR", "12.5", self.superuser)  # no-op
        self.ev("rate.set", self.superuser, None, "payroll")
        pc.delete_rate(m, "SAR", actor=self.superuser)
        self.ev("rate.deleted", self.superuser, None, "payroll")

        pc.save_rates(self.department, m, "7", [{"min_leads": 2, "amount": "5"}],
                      self.superuser, today=self.today)
        e = self.ev("rates.saved", self.superuser, None, "payroll")
        self.assertEqual((e.data["american_lead_price"], e.data["steps"]), ("7.00", 1))


class AdvanceEventTests(EventAssertions, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.cur = period_key_for(date.today(), AttendanceSettings.get().period_start_day)
        make_basic(self.agent, date(2020, 1, 1), 3000)
        self.hr = User.objects.create_user(username="hr", password="x", email="hr@t.com",
                                           role=UserTypes.HR, project=self.project,
                                           department=self.department)

    def req(self):
        return advances.request_advance(self.agent, self.agent, "1000", 3, self.cur, "r")

    def test_emit_lifecycle(self):
        adv = self.req()
        e = self.ev("advance.requested", self.agent, self.agent, "advances")
        self.assertEqual((e.data["amount"], e.target_uuid), ("1000.00", adv.pk))
        advances.approve_advance(self.hr, adv, "ok")
        e = self.ev("advance.approved", self.hr, self.agent, "advances")
        self.assertEqual(e.data["note"], "ok")
        advances.cancel_advance(self.hr, adv, "oops")
        e = self.ev("advance.cancelled", self.hr, self.agent, "advances")
        self.assertEqual(e.data["reason"], "oops")
        self.assertFalse(ActivityEvent.objects.filter(verb="entry.reversed").exists())

        a2 = self.req()
        advances.reject_advance(self.hr, a2, "no")
        self.ev("advance.rejected", self.hr, self.agent, "advances")
        a3 = self.req()
        advances.withdraw_advance(self.agent, a3)
        self.ev("advance.withdrawn", self.agent, self.agent, "advances")


class TreasuryEventTests(EventAssertions, BaseUserTestCase):
    def test_entries_and_groups(self):
        su = self.superuser
        entry = ledger.add_entry(su, "out", "operating", "300", date(2026, 10, 15), "Rent")
        e = self.ev("entry.added", su, None, "treasury")
        self.assertEqual((e.data["amount"], e.target_label, e.target_uuid), ("300.00", "Rent", entry.pk))
        ledger.reverse_entry(su, entry, "mistake")
        e = self.ev("entry.reversed", su, None, "treasury")
        self.assertEqual(e.data["reason"], "mistake")

        g = ledger.create_group(su, "Ops", [self.project.pk])
        self.ev("group.created", su, None, "treasury")
        ledger.update_group(g, name="Ops", project_ids=[self.project.pk], actor=su)  # no-op
        self.assertFalse(ActivityEvent.objects.filter(verb="group.updated").exists())
        ledger.update_group(g, name="Ops2", actor=su)
        self.ev("group.updated", su, None, "treasury")
        ledger.delete_group(g, actor=su)
        e = self.ev("group.deleted", su, None, "treasury")
        self.assertEqual(e.target_label, "Ops2")
        self.assertFalse(ProjectGroup.objects.exists())

    def test_import_events(self):
        b = importer.import_rows(self.superuser, [row(), row()], None)
        e = self.ev("import.done", self.superuser, None, "treasury")
        self.assertEqual((e.data["count"], e.data["total"]), (2, "200.00"))
        importer.reverse_batch(self.superuser, b, "bad")
        e = self.ev("import.reversed", self.superuser, None, "treasury")
        self.assertEqual(e.data["count"], 2)
        self.assertFalse(ActivityEvent.objects.filter(verb="entry.reversed").exists())
