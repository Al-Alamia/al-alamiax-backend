from apps.reports.models import ReportField, ReportSection, ReportType
from apps.reports.types import FieldKind
from apps.users.models import Department
from apps.users.tests.base import BaseUserTestCase


class ReportsTestCase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.marketing = Department.objects.create(name="Marketing", code="marketing")

    def make_type(self, frequency="daily", departments=None, sections=None, **kwargs):
        rt = ReportType.objects.create(
            name=kwargs.pop("name", f"Report {ReportType.objects.count()}"),
            frequency=frequency, **kwargs)
        rt.departments.set(departments if departments is not None else [self.marketing])
        if sections is None:
            sections = [("S", [("n", FieldKind.NUMBER, True),
                               ("t", FieldKind.TEXT, False),
                               ("a", FieldKind.ACCOUNTS, False)])]
        for s_order, (s_name, fields) in enumerate(sections):
            section = ReportSection.objects.create(report_type=rt, name=s_name, order=s_order)
            for f_order, (label, kind, required) in enumerate(fields):
                ReportField.objects.create(
                    section=section, label=label, kind=kind, required=required, order=f_order)
        return rt
