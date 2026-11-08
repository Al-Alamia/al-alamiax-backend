import calendar
from datetime import date, timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate

from apps.teams.permissions import supervised_users
from apps.users.models import Lead, Project, User
from apps.users.types import LeadStatuses

NO_PROJECT_NAME = "—"
DEFAULT_COLOR = "#64748b"


def _display_name(user):
    return f"{user.first_name} {user.last_name}".strip() or user.username


def date_range(mode: str, d: date):
    if mode == "day":
        return d, d
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=1), d.replace(day=last)


def build_dashboard(viewer, mode: str, d: date) -> dict:
    start, end = date_range(mode, d)
    scope_ids = supervised_users(viewer).values("pk")
    leads = Lead.objects.filter(
        user__in=scope_ids,
        date__date__gte=start,
        date__date__lte=end,
    )

    by_user = {
        r["user"]: r
        for r in leads.values("user").annotate(
            total=Count("pk"),
            subscribers=Count("pk", filter=Q(status=LeadStatuses.SUBSCRIBER)),
        )
    }
    total = sum(r["total"] for r in by_user.values())
    average = f"{total / len(by_user):.2f}" if by_user else "0.00"

    project_totals = {r["project"]: r["total"] for r in leads.values("project").annotate(total=Count("pk"))}
    meta = {p.pk: p for p in Project.objects.filter(pk__in=[k for k in project_totals if k])}
    projects = []
    for pk, count in project_totals.items():
        p = meta.get(pk)
        projects.append({
            "uuid": str(p.pk) if p else None,
            "name": p.name if p else NO_PROJECT_NAME,
            "color": (p.color if p else None) or DEFAULT_COLOR,
            "total": count,
        })
    projects.sort(key=lambda x: (-x["total"], x["name"]))

    series = []
    if mode == "month":
        per_day = {
            r["day"]: r["total"]
            for r in leads.annotate(day=TruncDate("date")).values("day").annotate(total=Count("pk"))
        }
        day = start
        while day <= end:
            series.append({"date": day.isoformat(), "total": per_day.get(day, 0)})
            day += timedelta(days=1)

    users_qs = (
        User.objects.filter(pk__in=scope_ids)
        .filter(Q(department__code="marketing") | Q(pk__in=list(by_user)))
        .select_related("project", "department")
    )
    users = []
    for u in users_qs:
        agg = by_user.get(u.pk, {})
        users.append({
            "uuid": str(u.pk),
            "name": _display_name(u),
            "project": u.project.name if u.project_id else None,
            "department": u.department.name if u.department_id else None,
            "total": agg.get("total", 0),
            "subscribers": agg.get("subscribers", 0),
        })
    users.sort(key=lambda x: (-x["total"], x["name"].lower()))

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "total": total,
        "average": average,
        "projects": projects,
        "series": series,
        "users": users,
    }
