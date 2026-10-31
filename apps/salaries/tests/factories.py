from datetime import date, datetime, time
from decimal import Decimal

from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.services import period_bounds
from apps.monthly_basic.types import BasicStatus
from apps.subscriptions.tests.factories import make_lead

KEY = "2026-10"
MONTH = date(2026, 10, 1)


def window():
    return period_bounds(KEY)


def make_lead_on(creator, day: date, **kw):
    return make_lead(creator, date=datetime.combine(day, time(10)), **kw)


def give_basic(user, net):
    return MonthlyBasic.objects.create(
        user=user, period=KEY, status=BasicStatus.GIVEN, net=Decimal(net), basic=Decimal(net))
