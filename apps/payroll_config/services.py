from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.teams.services import month_start

from .models import BasicSalary, DailyBonusStep, DepartmentRates, ExchangeRate

MAX_STEPS = 10


class ConfigError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class MissingRate(ConfigError):
    def __init__(self, month):
        self.month = month
        super().__init__("missing_rate", f"No exchange rate set for {month:%Y-%m}.")


def _check_not_past(month, today):
    if month < month_start(today or date.today()):
        raise ConfigError("past_month", "Cannot change this setting for a past month.")


def basic_for(user, month):
    entry = (BasicSalary.objects.filter(user=user, effective_from__lte=month_start(month))
             .order_by("-effective_from").first())
    return entry.amount if entry else None


def set_basic(user, month, amount, note, by, *, today=None):
    month = month_start(month)
    _check_not_past(month, today)
    amount = Decimal(str(amount))
    if amount < 0:
        raise ConfigError("invalid", "Amount must be zero or more.")
    entry, _ = BasicSalary.objects.update_or_create(
        user=user, effective_from=month,
        defaults={"amount": amount, "note": note or "", "created_by": by})
    return entry


def rate_for(month):
    month = month_start(month)
    rate = ExchangeRate.objects.filter(month=month).first()
    if rate is None:
        raise MissingRate(month)
    return rate.sar_to_egp


def set_rate(month, sar_to_egp, by):
    sar_to_egp = Decimal(str(sar_to_egp))
    if sar_to_egp <= 0:
        raise ConfigError("invalid", "Rate must be greater than zero.")
    rate, _ = ExchangeRate.objects.update_or_create(
        month=month_start(month), defaults={"sar_to_egp": sar_to_egp, "created_by": by})
    return rate


def delete_rate(month):
    deleted, _ = ExchangeRate.objects.filter(month=month_start(month)).delete()
    if not deleted:
        raise ConfigError("not_found", "No exchange rate for this month.")


def rates_for(department, month):
    return (DepartmentRates.objects
            .filter(department=department, effective_from__lte=month_start(month))
            .order_by("-effective_from").first())


def _validate_steps(steps):
    if len(steps) > MAX_STEPS:
        raise ConfigError("invalid", f"At most {MAX_STEPS} steps are allowed.")
    out = []
    for s in steps:
        try:
            min_leads = int(s["min_leads"])
            amount = Decimal(str(s["amount"]))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise ConfigError("invalid", "Each step needs min_leads and amount.")
        if min_leads < 1:
            raise ConfigError("invalid", "min_leads must be at least 1.")
        if amount < 0:
            raise ConfigError("invalid", "Step amount must be zero or more.")
        out.append((min_leads, amount))
    out.sort(key=lambda x: x[0])
    for prev, cur in zip(out, out[1:]):
        if prev[0] == cur[0]:
            raise ConfigError("invalid", "min_leads values must be distinct.")
        if cur[1] < prev[1]:
            raise ConfigError("invalid", "Amounts must not decrease as min_leads increases.")
    return out


def save_rates(department, month, american_lead_price, steps, by, *, today=None):
    month = month_start(month)
    _check_not_past(month, today)
    price = Decimal(str(american_lead_price))
    if price < 0:
        raise ConfigError("invalid", "American lead price must be zero or more.")
    normalized = _validate_steps(steps)
    with transaction.atomic():
        rates, _ = DepartmentRates.objects.update_or_create(
            department=department, effective_from=month,
            defaults={"american_lead_price": price, "created_by": by})
        rates.steps.all().delete()
        DailyBonusStep.objects.bulk_create(
            [DailyBonusStep(rates=rates, min_leads=m, amount=a) for m, a in normalized])
    return rates


def daily_bonus(rates, leads_in_day):
    if rates is None:
        return Decimal("0")
    step = (rates.steps.filter(min_leads__lte=leads_in_day)
            .order_by("-min_leads").first())
    return step.amount if step else Decimal("0")


def copy_basic_salaries(apps, today):
    """Data-migration helper: copy legacy UserCommissionDetails.basic into BasicSalary."""
    Legacy = apps.get_model("commission", "UserCommissionDetails")
    Basic = apps.get_model("payroll_config", "BasicSalary")
    month = month_start(today)
    count = 0
    for row in Legacy.objects.filter(basic__gt=0):
        _, created = Basic.objects.get_or_create(
            user_id=row.user_id, effective_from=month, defaults={"amount": row.basic})
        count += created
    return count
