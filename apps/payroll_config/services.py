from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from apps.teams.services import month_start

from .models import RATE_CURRENCIES, BasicSalary, DailyBonusStep, DepartmentRates, ExchangeRate

MAX_STEPS = 10


class ConfigError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class MissingRate(ConfigError):
    def __init__(self, month, currency="SAR"):
        self.month = month
        self.currency = currency
        super().__init__("missing_rate", f"No {currency} exchange rate for {month:%Y-%m}.")


def _parse_decimal(value, field, *, places, upper, positive=False):
    """Parse value to a finite Decimal within bounds, else ConfigError('invalid')."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ConfigError("invalid", f"{field} must be a number.")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise ConfigError("invalid", f"{field} must be a number.")
    if not d.is_finite():
        raise ConfigError("invalid", f"{field} must be a finite number.")
    if positive and d <= 0:
        raise ConfigError("invalid", f"{field} must be greater than zero.")
    if not positive and d < 0:
        raise ConfigError("invalid", f"{field} must be zero or more.")
    if d >= upper:
        raise ConfigError("invalid", f"{field} is too large.")
    if d != d.quantize(Decimal(1).scaleb(-places)):
        raise ConfigError("invalid", f"{field} allows at most {places} decimal places.")
    return d


def _money(value, field):
    return _parse_decimal(value, field, places=2, upper=Decimal(10) ** 10)


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
    amount = _money(amount, "amount")
    entry, _ = BasicSalary.objects.update_or_create(
        user=user, effective_from=month,
        defaults={"amount": amount, "note": note or "", "created_by": by})
    return entry


def _check_currency(currency):
    if currency not in RATE_CURRENCIES:
        raise ConfigError("invalid", f"currency must be one of {', '.join(RATE_CURRENCIES)}.")


def rate_for(month, currency="SAR"):
    if currency == "EGP":
        return Decimal("1")
    month = month_start(month)
    rate = ExchangeRate.objects.filter(month=month, currency=currency).first()
    if rate is None:
        raise MissingRate(month, currency)
    return rate.rate_to_egp


def set_rate(month, currency, rate_to_egp, by):
    _check_currency(currency)
    rate_to_egp = _parse_decimal(
        rate_to_egp, "rate_to_egp", places=4, upper=Decimal(1000000), positive=True)
    rate, _ = ExchangeRate.objects.update_or_create(
        month=month_start(month), currency=currency,
        defaults={"rate_to_egp": rate_to_egp, "created_by": by})
    return rate


def delete_rate(month, currency):
    _check_currency(currency)
    deleted, _ = ExchangeRate.objects.filter(
        month=month_start(month), currency=currency).delete()
    if not deleted:
        raise ConfigError("not_found", "No exchange rate for this month and currency.")


def to_sar(amount, currency, on):
    if currency == "SAR":
        return amount
    return (amount * rate_for(on, currency) / rate_for(on, "SAR")).quantize(
        Decimal("0.01"), ROUND_HALF_UP)


def rates_for(department, month):
    return (DepartmentRates.objects
            .filter(department=department, effective_from__lte=month_start(month))
            .order_by("-effective_from").first())


def _validate_steps(steps):
    if not isinstance(steps, (list, tuple)):
        raise ConfigError("invalid", "steps must be a list.")
    if len(steps) > MAX_STEPS:
        raise ConfigError("invalid", f"At most {MAX_STEPS} steps are allowed.")
    out = []
    for s in steps:
        if not isinstance(s, dict) or "min_leads" not in s or "amount" not in s:
            raise ConfigError("invalid", "Each step needs min_leads and amount.")
        min_leads = s["min_leads"]
        if isinstance(min_leads, str) and min_leads.strip().isdigit():
            min_leads = int(min_leads)
        if isinstance(min_leads, bool) or not isinstance(min_leads, int) or min_leads < 1:
            raise ConfigError("invalid", "min_leads must be an integer of at least 1.")
        if min_leads >= 2 ** 31:
            raise ConfigError("invalid", "min_leads is too large.")
        amount = _money(s["amount"], "step amount")
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
    price = _money(american_lead_price, "american_lead_price")
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
