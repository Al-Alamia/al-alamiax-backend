from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.users.tests.base import BaseUserTestCase
from apps.users.types import LeadUpdateTypes
from apps.subscriptions.types import SubscriptionStatus
from apps.subscriptions.models import Payment
from apps.subscriptions.tests.factories import make_lead, make_subscription, make_payment


class SubscriptionModelTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.lead = make_lead(self.superuser)

    def test_status_active(self):
        sub = make_subscription(self.lead, self.agent)
        self.assertEqual(sub.status(), SubscriptionStatus.ACTIVE)

    def test_status_expired(self):
        today = date.today()
        sub = make_subscription(self.lead, self.agent, start_date=today - timedelta(days=30),
                                end_date=today - timedelta(days=1))
        self.assertEqual(sub.status(), SubscriptionStatus.EXPIRED)

    def test_status_cancelled_wins(self):
        from django.utils.timezone import now
        sub = make_subscription(self.lead, self.agent, cancelled_at=now())
        self.assertEqual(sub.status(), SubscriptionStatus.CANCELLED)

    def test_status_today_argument(self):
        sub = make_subscription(self.lead, self.agent)
        self.assertEqual(sub.status(today=sub.end_date + timedelta(days=1)), SubscriptionStatus.EXPIRED)
        self.assertEqual(sub.status(today=sub.end_date), SubscriptionStatus.ACTIVE)

    def test_total_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_subscription(self.lead, self.agent, total_amount=Decimal("0"))

    def test_end_before_start_rejected(self):
        today = date.today()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_subscription(self.lead, self.agent, start_date=today, end_date=today - timedelta(days=1))

    def test_payment_amount_positive(self):
        sub = make_subscription(self.lead, self.agent)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_payment(sub, Decimal("0"), date.today())

    def test_payment_created(self):
        sub = make_subscription(self.lead, self.agent)
        p = make_payment(sub, Decimal("100"), date.today())
        self.assertEqual(list(sub.payments.all()), [p])
        self.assertIsInstance(p, Payment)

    def test_lead_update_type(self):
        self.assertEqual(LeadUpdateTypes.SUBSCRIPTION, "subscription")
        self.assertEqual(LeadUpdateTypes.PAYMENT, "payment")
