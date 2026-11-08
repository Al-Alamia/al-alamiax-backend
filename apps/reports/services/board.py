from collections import defaultdict
from datetime import date
from decimal import Decimal

from apps.teams.permissions import supervised_users
from apps.users.models import User

from ..models import ReportSubmission, ReportValue
from ..types import FieldKind, SubmissionStatus
from .audience import not_working_ids, required_users
from .periods import period_for
from .submissions import value_payload

_ORDER = {
    SubmissionStatus.MISSING: 0,
    SubmissionStatus.LATE: 1,
    SubmissionStatus.SUBMITTED: 2,
    SubmissionStatus.NOT_REQUIRED: 3,
}
_ZERO = Decimal("0.00")


def _name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def _ref(obj):
    return None if obj is None else {"uuid": str(obj.uuid), "name": obj.name}


def _money(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01")))


def build_board(report_type, viewer, any_date: date, today: date, project_uuid=None) -> dict:
    start, end = period_for(report_type, any_date)

    scope_ids = set(supervised_users(viewer).values_list("pk", flat=True))
    submissions = list(
        ReportSubmission.objects
        .filter(report_type=report_type, period_start=start, user_id__in=scope_ids)
        .select_related("department", "project"))
    by_user = {s.user_id: s for s in submissions}
    required_ids = set(required_users(report_type).filter(pk__in=scope_ids)
                       .values_list("pk", flat=True))
    row_ids = required_ids | set(by_user)
    users = {u.pk: u for u in
             User.objects.filter(pk__in=row_ids).select_related("department", "project")}
    idle = not_working_ids(row_ids - set(by_user), start, end, today)

    # values, grouped per submission
    values_by_sub = defaultdict(list)
    for v in (ReportValue.objects.filter(submission__in=[s.pk for s in submissions])
              .select_related("field")):
        values_by_sub[v.submission_id].append(v)
    used_field_ids = {v.field_id for vs in values_by_sub.values() for v in vs}

    sections = []
    for section in report_type.sections.prefetch_related("fields"):
        fields = [f for f in section.fields.all()
                  if (section.is_active and f.is_active) or f.pk in used_field_ids]
        if not fields:
            continue
        sections.append({
            "uuid": str(section.uuid), "name": section.name, "is_active": section.is_active,
            "fields": [{"uuid": str(f.uuid), "label": f.label, "kind": f.kind,
                        "required": f.required, "is_active": f.is_active} for f in fields],
        })

    rows = []
    summary = {"submitted": 0, "late": 0, "missing": 0, "not_required": 0}
    field_totals: dict = {}
    for uid in row_ids:
        user = users[uid]
        sub = by_user.get(uid)
        if sub is not None:
            project, department = sub.project, sub.department
            status = SubmissionStatus.LATE if sub.is_late else SubmissionStatus.SUBMITTED
        else:
            project, department = user.project, user.department
            status = (SubmissionStatus.NOT_REQUIRED if uid in idle
                      else SubmissionStatus.MISSING)
        if project_uuid is not None and (project is None or str(project.uuid) != str(project_uuid)):
            continue

        values, section_totals, total = {}, {}, _ZERO
        for v in (values_by_sub.get(sub.pk, []) if sub else []):
            values[str(v.field_id)] = value_payload(v)
            if v.field.kind == FieldKind.NUMBER and v.number is not None:
                sec = str(v.field.section_id)
                section_totals[sec] = section_totals.get(sec, _ZERO) + v.number
                total += v.number
                fid = str(v.field_id)
                field_totals[fid] = field_totals.get(fid, _ZERO) + v.number
        summary[status.value] += 1
        rows.append({
            "user": {"uuid": str(user.uuid), "name": _name(user),
                     "project": _ref(project), "department": _ref(department)},
            "status": status.value,
            "submission": str(sub.uuid) if sub else None,
            "values": values,
            "section_totals": {k: _money(x) for k, x in section_totals.items()},
            "total": _money(total),
            "_key": (_ORDER[status], _name(user).lower()),
        })

    rows.sort(key=lambda r: r.pop("_key"))
    return {
        "period": {"start": start, "end": end},
        "sections": sections,
        "rows": rows,
        "summary": {**summary, "field_totals": {k: _money(v) for k, v in field_totals.items()}},
    }
