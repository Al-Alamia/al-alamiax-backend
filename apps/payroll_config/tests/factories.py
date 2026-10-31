from apps.payroll_config.models import BasicSalary, DepartmentRates, ExchangeRate


def make_basic(user, month, amount, note=""):
    return BasicSalary.objects.create(
        user=user, effective_from=month, amount=amount, note=note)


def make_rate(month, value, currency="SAR"):
    return ExchangeRate.objects.create(month=month, currency=currency, rate_to_egp=value)


def make_rates(department, month, price=0):
    return DepartmentRates.objects.create(
        department=department, effective_from=month, american_lead_price=price)
