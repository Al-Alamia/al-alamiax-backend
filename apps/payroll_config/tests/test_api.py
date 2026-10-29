from datetime import date

from apps.payroll_config.models import BasicSalary
from apps.payroll_config.tests.factories import make_basic, make_rate, make_rates
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

B = "/api/payroll"
STEPS = [{"min_leads": 3, "amount": "10"}, {"min_leads": 6, "amount": "25.50"}]


def mk(name, role, dept):
    return User.objects.create_user(username=name, password="x", role=role, department=dept)


def this_month():
    return date.today().strftime("%Y-%m")


def past_month():
    t = date.today()
    y, m = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
    return f"{y:04d}-{m:02d}"


class PayrollApiBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.dept = Department.objects.create(name="Sales", code="sales")
        self.owner = self.superuser
        self.top = mk("topowner", UserTypes.OWNER, self.dept)
        self.hr = mk("hr", UserTypes.HR, self.dept)
        self.mgr = mk("mgr", UserTypes.MANAGER, self.dept)

    def call(self, method, user, url, data=None):
        self.authenticate_as(user)
        if method == "get":
            return self.client.get(url, data or {})
        return getattr(self.client, method)(url, data, format="json")


class SalaryApiTests(PayrollApiBase):
    def test_hr_sets_and_reads_salary(self):
        r = self.call("put", self.hr, f"{B}/salaries/{self.agent.uuid}/{this_month()}",
                      {"amount": "6000", "note": "raise"})
        self.assertEqual(r.status_code, 200)
        r = self.call("get", self.hr, f"{B}/salaries", {"user": str(self.agent.uuid)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["current"], {"amount": "6000.00", "effective_from": this_month()})
        self.assertEqual(len(r.data["history"]), 1)
        self.assertEqual(r.data["history"][0]["note"], "raise")
        self.assertEqual(r.data["history"][0]["created_by"]["uuid"], str(self.hr.uuid))

    def test_hr_cannot_edit_own(self):
        r = self.call("put", self.hr, f"{B}/salaries/{self.hr.uuid}/{this_month()}", {"amount": "1"})
        self.assertEqual(r.status_code, 403)

    def test_owner_edits_own(self):
        for u in (self.owner, self.top):
            r = self.call("put", u, f"{B}/salaries/{u.uuid}/{this_month()}", {"amount": "1"})
            self.assertEqual(r.status_code, 200)

    def test_past_month(self):
        r = self.call("put", self.hr, f"{B}/salaries/{self.agent.uuid}/{past_month()}", {"amount": "1"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "past_month"))

    def test_invalid_amount_and_month(self):
        url = f"{B}/salaries/{self.agent.uuid}/{this_month()}"
        for bad in ("-1", "abc", None):
            r = self.call("put", self.hr, url, {"amount": bad})
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.call("put", self.hr, f"{B}/salaries/{self.agent.uuid}/2026-13", {"amount": "1"})
        self.assertEqual(r.status_code, 400)

    def test_manager_gets_404(self):
        make_basic(self.agent, date.today().replace(day=1), 100)
        r = self.call("get", self.mgr, f"{B}/salaries", {"user": str(self.agent.uuid)})
        self.assertEqual(r.status_code, 404)

    def test_agent_own_read_and_no_edit(self):
        make_basic(self.agent, date.today().replace(day=1), 100)
        r = self.call("get", self.agent, f"{B}/salaries", {"user": str(self.agent.uuid)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["current"]["amount"], "100.00")
        r = self.call("put", self.agent, f"{B}/salaries/{self.agent.uuid}/{this_month()}", {"amount": "9"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(BasicSalary.objects.get(user=self.agent).amount, 100)

    def test_no_entries(self):
        r = self.call("get", self.hr, f"{B}/salaries", {"user": str(self.agent.uuid)})
        self.assertEqual(r.data, {"current": None, "history": []})

    def test_unknown_user_404(self):
        r = self.call("get", self.hr, f"{B}/salaries", {"user": "bad"})
        self.assertEqual(r.status_code, 404)


class RatesApiTests(PayrollApiBase):
    def test_list_year(self):
        make_rate(date(2026, 3, 1), "12.5")
        r = self.call("get", self.hr, f"{B}/rates", {"year": 2026})
        self.assertEqual(r.status_code, 200)
        res = r.data["results"]
        self.assertEqual(len(res), 12)
        self.assertEqual(res[2], {"month": "2026-03", "sar_to_egp": "12.5000"})
        self.assertIsNone(res[0]["sar_to_egp"])

    def test_invalid_year(self):
        r = self.call("get", self.hr, f"{B}/rates", {"year": "abc"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_hr_put_past_allowed(self):
        r = self.call("put", self.hr, f"{B}/rates/2025-03", {"sar_to_egp": "13.1234"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["sar_to_egp"], "13.1234")

    def test_invalid_rates(self):
        for bad in ("0", "1.12345", "x"):
            r = self.call("put", self.hr, f"{B}/rates/2025-03", {"sar_to_egp": bad})
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_roles(self):
        self.assertEqual(self.call("put", self.mgr, f"{B}/rates/2025-03", {"sar_to_egp": "1"}).status_code, 403)
        self.assertEqual(self.call("get", self.mgr, f"{B}/rates").status_code, 200)
        self.assertEqual(self.call("get", self.agent, f"{B}/rates").status_code, 403)
        self.assertEqual(self.call("delete", self.mgr, f"{B}/rates/2025-03").status_code, 403)

    def test_delete(self):
        self.assertEqual(self.call("delete", self.hr, f"{B}/rates/2025-03").status_code, 404)
        make_rate(date(2025, 3, 1), 2)
        self.assertEqual(self.call("delete", self.hr, f"{B}/rates/2025-03").status_code, 204)


class DepartmentRatesApiTests(PayrollApiBase):
    def url(self, month):
        return f"{B}/department-rates/{self.dept.uuid}/{month}"

    def test_put_and_get(self):
        r = self.call("put", self.hr, self.url(this_month()),
                      {"american_lead_price": "5", "steps": STEPS})
        self.assertEqual(r.status_code, 200)
        r = self.call("get", self.mgr, f"{B}/department-rates",
                      {"department": str(self.dept.uuid), "month": this_month()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["sheet"], {
            "effective_from": this_month(), "american_lead_price": "5.00",
            "steps": [{"min_leads": 3, "amount": "10.00"}, {"min_leads": 6, "amount": "25.50"}]})
        self.assertEqual(r.data["versions"], [this_month()])

    def test_get_empty(self):
        r = self.call("get", self.hr, f"{B}/department-rates", {"department": str(self.dept.uuid)})
        self.assertEqual(r.data, {"sheet": None, "versions": []})

    def test_versions_newest_first(self):
        make_rates(self.dept, date(2026, 1, 1))
        make_rates(self.dept, date(2026, 5, 1))
        r = self.call("get", self.hr, f"{B}/department-rates",
                      {"department": str(self.dept.uuid), "month": "2026-03"})
        self.assertEqual(r.data["sheet"]["effective_from"], "2026-01")
        self.assertEqual(r.data["versions"], ["2026-05", "2026-01"])

    def test_manager_put_403_agent_get_403(self):
        body = {"american_lead_price": "5", "steps": []}
        self.assertEqual(self.call("put", self.mgr, self.url(this_month()), body).status_code, 403)
        r = self.call("get", self.agent, f"{B}/department-rates", {"department": str(self.dept.uuid)})
        self.assertEqual(r.status_code, 403)

    def test_past_month_and_invalid(self):
        r = self.call("put", self.hr, self.url(past_month()), {"american_lead_price": "5", "steps": []})
        self.assertEqual((r.status_code, r.data["type"]), (400, "past_month"))
        r = self.call("put", self.hr, self.url(this_month()),
                      {"american_lead_price": "5", "steps": [{"min_leads": 1, "amount": "9"}, {"min_leads": 2, "amount": "1"}]})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_unknown_department_404(self):
        r = self.call("put", self.hr, f"{B}/department-rates/{self.hr.uuid}/{this_month()}",
                      {"american_lead_price": "5", "steps": []})
        self.assertEqual(r.status_code, 404)
        r = self.call("get", self.hr, f"{B}/department-rates", {"department": str(self.hr.uuid)})
        self.assertEqual(r.status_code, 404)


class MetaTests(PayrollApiBase):
    def test_meta(self):
        expect = {
            self.hr: (True, True, True), self.top: (True, True, True),
            self.mgr: (True, False, False), self.agent: (False, False, False)}
        for user, (v, e, s) in expect.items():
            r = self.call("get", user, f"{B}/meta")
            self.assertEqual(
                r.data, {"can_view_rates": v, "can_edit_rates": e, "can_edit_salaries": s}, user.username)
