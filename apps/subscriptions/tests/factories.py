from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from apps.subscriptions.models import Payment, Subscription
from apps.users.models import Department, Lead, LeadAssignment
from apps.users.types import DepartmentCodes

_seq = count(1)


def _dept(code, name):
    return Department.objects.get_or_create(code=code, defaults={"name": name})[0]


def sales_dept():
    return _dept(DepartmentCodes.SALES, "Sales")


def marketing_dept():
    return _dept(DepartmentCodes.MARKETING, "Marketing")


def make_lead(creator, **kw) -> Lead:
    n = next(_seq)
    data = {"user": creator, "phone": f"+9665000{n:05d}", "name": f"Lead {n}", "stock_market": "saudi"}
    data.update(kw)
    return Lead.objects.create(**data)


def assign(lead, agent, kind="sales", by=None, active=True) -> LeadAssignment:
    return LeadAssignment.objects.create(lead=lead, agent=agent, kind=kind, assigned_by=by, is_active=active)


def make_subscription(lead, seller, **kw) -> Subscription:
    today = date.today()
    data = {
        "lead": lead, "seller": seller, "kind": "new", "plan_name": "Gold", "market": "saudi",
        "currency": "SAR", "total_amount": Decimal("1000"),
        "start_date": today, "end_date": today + timedelta(days=365),
    }
    data.update(kw)
    return Subscription.objects.create(**data)


def make_payment(sub, amount, paid_on, **kw) -> Payment:
    data = {"subscription": sub, "amount": Decimal(amount), "paid_on": paid_on, "method": "cash"}
    data.update(kw)
    return Payment.objects.create(**data)
