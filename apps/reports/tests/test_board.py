from datetime import date

from django.utils import timezone

from apps.attendance.models import AttendanceDay
from apps.attendance.types import DayStatus
from apps.reports.models import ReportField, ReportSection, ReportSubmission, ReportValue
from apps.reports.services import board
from apps.reports.services.submissions import save_submission
from apps.reports.tests.base import ReportsTestCase
from apps.teams.models import Team
from apps.users.models import Department, Project, User
from apps.users.types import UserTypes

TODAY = date(2026, 11, 8)


class BoardTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.rt = self.make_type("daily")
        self.num = ReportField.objects.get(section__report_type=self.rt, label="n")
        self.txt = ReportField.objects.get(section__report_type=self.rt, label="t")
        self.section = self.num.section

    def mk(self, name, role=UserTypes.AGENT, **kw):
        kw.setdefault("department", self.marketing)
        kw.setdefault("project", self.project)
        return User.objects.create_user(username=name, password="x", role=role, **kw)

    def submit(self, user, values=None, today=TODAY, when=TODAY):
        return save_submission(
            self.rt, user, when, values or {str(self.num.uuid): 5}, today)

    def build(self, viewer=None, **kw):
        return board.build_board(self.rt, viewer or self.superuser, TODAY, TODAY, **kw)

    def by_name(self, data):
        return {r["user"]["name"]: r for r in data["rows"]}

    def test_statuses_and_sorting(self):
        a = self.mk("a_sub")
        b = self.mk("b_late")
        c = self.mk("c_miss")
        d = self.mk("d_leave")
        self.submit(a)
        save_submission(self.rt, b, date(2026, 11, 7), {str(self.num.uuid): 1}, TODAY)
        ReportSubmission.objects.filter(user=b).update(period_start=TODAY, period_end=TODAY)
        AttendanceDay.objects.create(
            user=d, date=TODAY, status=DayStatus.LEAVE, evaluated_at=timezone.now())
        data = self.build()
        rows = self.by_name(data)
        self.assertEqual(rows["a_sub"]["status"], "submitted")
        self.assertEqual(rows["b_late"]["status"], "late")
        self.assertEqual(rows["c_miss"]["status"], "missing")
        self.assertEqual(rows["d_leave"]["status"], "not_required")
        self.assertEqual([r["user"]["name"] for r in data["rows"]],
                         ["c_miss", "b_late", "a_sub", "d_leave"])
        self.assertEqual(data["summary"]["submitted"], 1)
        self.assertEqual(data["summary"]["late"], 1)
        self.assertEqual(data["summary"]["missing"], 1)
        self.assertEqual(data["summary"]["not_required"], 1)
        self.assertEqual(data["period"], {"start": TODAY, "end": TODAY})

    def test_row_shape_values_and_totals(self):
        u = self.mk("u", first_name="Ann", last_name="Lee")
        s = self.submit(u, {str(self.num.uuid): "5.5", str(self.txt.uuid): "hi"})
        row = self.build()["rows"][0]
        self.assertEqual(row["user"]["name"], "Ann Lee")
        self.assertEqual(row["user"]["project"], {"uuid": str(self.project.uuid), "name": "Test Project"})
        self.assertEqual(row["user"]["department"]["name"], "Marketing")
        self.assertEqual(row["submission"], str(s.uuid))
        self.assertEqual(row["values"][str(self.num.uuid)], "5.50")
        self.assertEqual(row["values"][str(self.txt.uuid)], "hi")
        self.assertEqual(row["section_totals"], {str(self.section.uuid): "5.50"})
        self.assertEqual(row["total"], "5.50")

    def test_section_totals_sum_only_number_fields(self):
        rt = self.make_type("daily", name="Two", sections=[
            ("S", [("n1", "number", False), ("n2", "number", False), ("t", "text", False)])])
        n1, n2, t = [ReportField.objects.get(section__report_type=rt, label=x)
                     for x in ("n1", "n2", "t")]
        u = self.mk("u")
        save_submission(rt, u, TODAY, {str(n1.uuid): 1, str(n2.uuid): "2.25", str(t.uuid): "99"}, TODAY)
        data = board.build_board(rt, self.superuser, TODAY, TODAY)
        row = data["rows"][0]
        self.assertEqual(row["total"], "3.25")
        self.assertEqual(row["section_totals"][str(n1.section.uuid)], "3.25")
        self.assertEqual(data["summary"]["field_totals"][str(n1.uuid)], "1.00")
        self.assertEqual(data["summary"]["field_totals"][str(n2.uuid)], "2.25")
        self.assertNotIn(str(t.uuid), data["summary"]["field_totals"])

    def test_manager_sees_own_department_only(self):
        mgr = self.mk("mgr", role=UserTypes.MANAGER)
        self.mk("in_dept")
        other = Department.objects.create(name="Other", code="other")
        self.rt.departments.add(other)
        self.mk("out_dept", department=other)
        names = {r["user"]["name"] for r in self.build(viewer=mgr)["rows"]}
        self.assertEqual(names, {"mgr", "in_dept"})

    def test_leader_sees_team_agents(self):
        leader = self.mk("lead", role=UserTypes.AGENT)
        mine = self.mk("mine")
        self.mk("notmine")
        team = Team.objects.create(name="T", department=self.marketing, leader=leader)
        team.agents.add(mine)
        names = {r["user"]["name"] for r in self.build(viewer=leader)["rows"]}
        self.assertEqual(names, {"lead", "mine"})

    def test_agent_sees_own_row_only(self):
        me = self.mk("me")
        self.mk("other")
        rows = self.build(viewer=me)["rows"]
        self.assertEqual([r["user"]["name"] for r in rows], ["me"])

    def test_project_filter(self):
        p2 = Project.objects.create(name="P2")
        self.mk("p1u")
        self.mk("p2u", project=p2)
        rows = self.build(project_uuid=p2.uuid)["rows"]
        self.assertEqual([r["user"]["name"] for r in rows], ["p2u"])

    def test_project_filter_uses_snapshot(self):
        p2 = Project.objects.create(name="P2")
        u = self.mk("mover")
        self.submit(u)
        u.project = p2
        u.save()
        row = self.build(project_uuid=self.project.uuid)["rows"][0]
        self.assertEqual(row["user"]["project"]["name"], "Test Project")
        self.assertEqual(self.build(project_uuid=p2.uuid)["rows"], [])

    def test_board_keeps_excluded_submitter(self):
        u = self.mk("ex")
        self.submit(u)
        self.rt.excluded_users.add(u)
        rows = self.by_name(self.build())
        self.assertEqual(rows["ex"]["status"], "submitted")

    def test_board_includes_inactive_field_with_values(self):
        u = self.mk("u")
        self.submit(u, {str(self.num.uuid): 3, str(self.txt.uuid): "x"})
        ReportField.objects.filter(pk=self.txt.pk).update(is_active=False)
        extra = ReportField.objects.create(
            section=self.section, label="gone", kind="number", is_active=False, order=9)
        data = self.build()
        fields = {f["uuid"]: f for f in data["sections"][0]["fields"]}
        self.assertIn(str(self.txt.uuid), fields)
        self.assertFalse(fields[str(self.txt.uuid)]["is_active"])
        self.assertNotIn(str(extra.uuid), fields)

    def test_inactive_section_with_values_included_without_omitted(self):
        u = self.mk("u")
        self.submit(u)
        ReportSection.objects.filter(pk=self.section.pk).update(is_active=False)
        data = self.build()
        self.assertEqual(len(data["sections"]), 1)
        self.assertFalse(data["sections"][0]["is_active"])
        ReportValue.objects.all().delete()
        self.assertEqual(self.build()["sections"], [])

    def test_query_count_does_not_grow_with_rows(self):
        for i in range(2):
            self.submit(self.mk(f"u{i}"))
        with self.assertNumQueries(self._count(2)):
            self.build()
        for i in range(2, 12):
            self.submit(self.mk(f"u{i}"))
        with self.assertNumQueries(self._count(2)):
            self.build()

    def _count(self, _):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        if not hasattr(self, "_n"):
            with CaptureQueriesContext(connection) as c:
                self.build()
            self._n = len(c)
        return self._n
