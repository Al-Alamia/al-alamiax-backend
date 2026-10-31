import datetime as dt
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.users.models import Project

from ..models import ProjectGroup, TreasuryEntry
from ..types import CATEGORIES_BY_DIRECTION, Category, Direction
from .errors import TreasuryError

ZERO = Decimal(0)
_UPPER = Decimal(10) ** 10
_TWO_DP = Decimal("0.01")
_ZERO_FIELD = DecimalField(max_digits=14, decimal_places=2)


def parse_amount(value, field="amount") -> Decimal:
    """Parse to a finite Decimal > 0, at most 2 dp, < 10^10; else TreasuryError('invalid')."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise TreasuryError("invalid", f"{field} must be a number.")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise TreasuryError("invalid", f"{field} must be a number.")
    if not d.is_finite():
        raise TreasuryError("invalid", f"{field} must be a finite number.")
    if d <= 0:
        raise TreasuryError("invalid", f"{field} must be greater than zero.")
    if d >= _UPPER:
        raise TreasuryError("invalid", f"{field} is too large.")
    if d != d.quantize(_TWO_DP):
        raise TreasuryError("invalid", f"{field} allows at most 2 decimal places.")
    return d


def _sum(qs):
    return qs.aggregate(t=Coalesce(Sum("amount"), Decimal(0), output_field=_ZERO_FIELD))["t"]


def _in_month(qs, month):
    if month is None:
        return qs
    return qs.filter(date__year=month.year, date__month=month.month)


def _outcome(qs):
    """out non-reversals minus in reversals."""
    return (_sum(qs.filter(direction=Direction.OUT, reverses__isnull=True))
            - _sum(qs.filter(direction=Direction.IN, reverses__isnull=False)))


def balance(month: Optional[dt.date]) -> dict:
    qs = _in_month(TreasuryEntry.objects.all(), month)
    income = (_sum(qs.filter(direction=Direction.IN, reverses__isnull=True))
              - _sum(qs.filter(direction=Direction.OUT, reverses__isnull=False)))
    outcome = _outcome(qs)
    return {"income": income, "outcome": outcome, "net": income - outcome}


def group_breakdown(month: Optional[dt.date]) -> list:
    qs = _in_month(TreasuryEntry.objects.all(), month)
    rows = [{"group": g, "outcome": _outcome(qs.filter(group=g))}
            for g in ProjectGroup.objects.order_by("name", "uuid")]
    rows.append({"group": None, "outcome": _outcome(qs.filter(group__isnull=True))})
    return rows


@transaction.atomic
def add_entry(by, direction, category, amount, date, details, group=None) -> TreasuryEntry:
    if direction not in (Direction.IN, Direction.OUT):
        raise TreasuryError("invalid", "Invalid direction.")
    if category == Category.ADVANCE:
        raise TreasuryError("invalid", "The advance category is system-only.")
    if category not in CATEGORIES_BY_DIRECTION[direction]:
        raise TreasuryError("invalid", "Category does not match the direction.")
    if group is not None and direction != Direction.OUT:
        raise TreasuryError("invalid", "A group can only be set on outcome entries.")
    amount = parse_amount(amount)
    if not isinstance(date, dt.date) or isinstance(date, dt.datetime):
        raise TreasuryError("invalid", "A valid date is required.")
    if date > dt.date.today():
        raise TreasuryError("invalid", "Date cannot be in the future.")
    details = details.strip() if isinstance(details, str) else ""
    if not 1 <= len(details) <= 250:
        raise TreasuryError("invalid", "Details must be 1-250 characters.")
    return TreasuryEntry.objects.create(
        direction=direction, category=category, amount=amount, date=date,
        details=details, group=group, created_by=by)


@transaction.atomic
def reverse_entry(by, entry, reason, *, allow_advance=False) -> TreasuryEntry:
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise TreasuryError("invalid", "A reason is required.")
    entry = TreasuryEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.reverses_id is not None:
        raise TreasuryError("is_reversal", "A reversal cannot be reversed.")
    if entry.reversed_at is not None:
        raise TreasuryError("already_reversed", "This entry is already reversed.")
    if entry.advance_id is not None and not allow_advance:
        raise TreasuryError("advance_entry", "Cancel the advance instead of reversing its entry.")
    reversal = TreasuryEntry.objects.create(
        direction=Direction.IN if entry.direction == Direction.OUT else Direction.OUT,
        category=entry.category, amount=entry.amount, date=dt.date.today(),
        details=("Reversal: " + entry.details)[:250], group=entry.group,
        advance=entry.advance, reverses=entry, created_by=by)
    entry.reversed_at = timezone.now()
    entry.reversal_reason = reason
    entry.save(update_fields=["reversed_at", "reversal_reason", "updated_at"])
    return reversal


def _clean_name(name, exclude_pk=None):
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= 100:
        raise TreasuryError("invalid", "Name must be 1-100 characters.")
    dup = ProjectGroup.objects.filter(name__iexact=name)
    if exclude_pk is not None:
        dup = dup.exclude(pk=exclude_pk)
    if dup.exists():
        raise TreasuryError("duplicate", "A group with this name already exists.")
    return name


def _projects(project_ids):
    try:
        ids = {i if isinstance(i, uuid.UUID) else uuid.UUID(str(i)) for i in (project_ids or [])}
    except (ValueError, AttributeError, TypeError):
        raise TreasuryError("invalid", "Invalid project ids.")
    projects = list(Project.objects.filter(pk__in=ids))
    if len(projects) != len(ids):
        raise TreasuryError("invalid", "Unknown project.")
    return projects


@transaction.atomic
def create_group(by, name, project_ids) -> ProjectGroup:
    name = _clean_name(name)
    projects = _projects(project_ids)
    group = ProjectGroup.objects.create(name=name, created_by=by)
    group.projects.set(projects)
    return group


@transaction.atomic
def update_group(group, name=None, project_ids=None) -> ProjectGroup:
    if name is not None:
        group.name = _clean_name(name, exclude_pk=group.pk)
        group.save(update_fields=["name", "updated_at"])
    if project_ids is not None:
        group.projects.set(_projects(project_ids))
    return group


@transaction.atomic
def delete_group(group) -> None:
    if TreasuryEntry.objects.filter(group=group).exists():
        raise TreasuryError("in_use", "This group is used by ledger entries.")
    group.delete()
