import datetime as dt
from decimal import Decimal

from rest_framework.exceptions import PermissionDenied

from apps.attendance.models import PeriodClose
from apps.subscriptions import services as svc
from apps.subscriptions.models import Payment, Subscription
from apps.subscriptions.services import SubscriptionError
from apps.subscriptions.tests.factories import (
    assign, make_lead, make_payment, make_subscription, marketing_dept, sales_dept,
)
from apps.teams.models import Team
from apps.users.models import LeadUpdate, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import LeadStatuses, LeadUpdateTypes, UserTypes

D = dt.date
TODAY = D.today()


def mk(username, role, dept):
    return User.objects.create_user(
        username=username, password="x", email=f"{username}@t.com", role=role,
        project=None, department=dept,
    )


def body(**kw):
    data = {
        "kind": "new", "plan_name": " Gold ", "market": "saudi", "currency": "SAR",
        "total_amount": "1000", "start_date": TODAY.isoformat(),
        "end_date": (TODAY + dt.timedelta(days=30)).isoformat(),
    }
    data.update(kw)
    return {k: v for k, v in data.items() if v is not ...}


class ServiceBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        sales, mkt = sales_dept(), marketing_dept()
        self.manager = mk("s_manager", UserTypes.MANAGER, sales)
        self.leader = mk("s_leader", UserTypes.AGENT, sales)
        self.a = mk("s_a", UserTypes.AGENT, sales)
        self.c = mk("s_c", UserTypes.AGENT, sales)
        self.b = mk("s_b", UserTypes.AGENT, sales)
        self.past = mk("s_past", UserTypes.AGENT, sales)
        self.m = mk("m_user", UserTypes.AGENT, mkt)
        team = Team.objects.create(name="T", department=sales, leader=self.leader)
        team.agents.add(self.a)
        self.lead = make_lead(self.m)
        assign(self.lead, self.a, "sales")
        assign(self.lead, self.c, "cs")
        assign(self.lead, self.past, "sales", active=False)

    def code(self, fn, *args):
        with self.assertRaises(SubscriptionError) as cm:
            fn(*args)
        return cm.exception.code

    def close_period(self, d):
        PeriodClose.objects.create(
            period=d.strftime("%Y-%m"), start=d.replace(day=1), end=d.replace(day=28),
            closed_by=self.superuser, closed_at=dt.datetime.now(),
        )


class CreateTests(ServiceBase):
    def test_agent_is_seller_and_lead_becomes_subscriber(self):
        sub = svc.create_subscription(self.a, self.lead, body(seller=str(self.c.pk)))
        self.assertEqual(sub.seller, self.a)
        self.assertEqual(sub.created_by, self.a)
        self.assertEqual(sub.plan_name, "Gold")
        self.assertEqual(sub.total_amount, Decimal("1000.00"))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatuses.SUBSCRIBER)
        ups = LeadUpdate.objects.filter(lead=self.lead)
        self.assertEqual(ups.filter(type=LeadUpdateTypes.STATUS).count(), 1)
        sub_up = ups.get(type=LeadUpdateTypes.SUBSCRIPTION)
        self.assertEqual(sub_up.to_value, "created: Gold 1000.00 SAR")

    def test_no_status_log_when_already_subscriber(self):
        self.lead.status = LeadStatuses.SUBSCRIBER
        self.lead.save()
        svc.create_subscription(self.a, self.lead, body())
        self.assertFalse(LeadUpdate.objects.filter(lead=self.lead, type=LeadUpdateTypes.STATUS).exists())

    def test_leader_may_pick_past_assignee(self):
        sub = svc.create_subscription(self.leader, self.lead, body(seller=str(self.past.pk)))
        self.assertEqual(sub.seller, self.past)

    def test_leader_seller_not_on_lead_invalid(self):
        self.assertEqual(self.code(svc.create_subscription, self.leader, self.lead, body(seller=str(self.b.pk))), "invalid")

    def test_leader_missing_or_bad_seller_invalid(self):
        self.assertEqual(self.code(svc.create_subscription, self.leader, self.lead, body()), "invalid")
        self.assertEqual(self.code(svc.create_subscription, self.leader, self.lead, body(seller="nope")), "invalid")

    def test_missing_market_invalid(self):
        # Review Focus 5
        with self.assertRaises(SubscriptionError) as cm:
            svc.create_subscription(self.a, self.lead, body(market=...))
        self.assertEqual(cm.exception.code, "invalid")
        self.assertIn("market", cm.exception.message)
        self.assertEqual(self.code(svc.create_subscription, self.a, self.lead, body(market="")), "invalid")
        self.assertEqual(self.code(svc.create_subscription, self.a, self.lead, body(market="mars")), "invalid")

    def test_other_invalid_fields(self):
        for kw in (
            {"kind": "x"}, {"currency": "EUR"}, {"plan_name": "  "}, {"plan_name": "x" * 101},
            {"start_date": "2026/01/01"}, {"start_date": ...}, {"end_date": (TODAY - dt.timedelta(days=1)).isoformat()},
        ):
            self.assertEqual(self.code(svc.create_subscription, self.a, self.lead, body(**kw)), "invalid", kw)
        self.assertEqual(Subscription.objects.count(), 0)

    def test_money_parsing(self):
        # Review Focus 3
        for bad in ("1,000", "10.123", "-5", "", None, "0", "abc", "1e3", 10 ** 10, "10000000000", True, [], "0.00"):
            self.assertEqual(
                self.code(svc.create_subscription, self.a, self.lead, body(total_amount=bad)), "invalid", repr(bad))
        sub = svc.create_subscription(self.a, self.lead, body(total_amount=12.5))
        self.assertEqual(sub.total_amount, Decimal("12.50"))
        sub = svc.create_subscription(self.a, self.lead, body(total_amount=500))
        self.assertEqual(sub.total_amount, Decimal("500.00"))

    def test_hidden_lead_denied(self):
        self.lead.is_hidden = True
        self.lead.save()
        with self.assertRaises(PermissionDenied):
            svc.create_subscription(self.a, self.lead, body())

    def test_unassigned_agent_denied(self):
        with self.assertRaises(PermissionDenied):
            svc.create_subscription(self.b, self.lead, body())


class UpdateTests(ServiceBase):
    def setUp(self):
        super().setUp()
        self.sub = make_subscription(self.lead, self.a)

    def test_update_logs(self):
        sub = svc.update_subscription(self.leader, self.sub, {"plan_name": "Silver"})
        self.assertEqual(sub.plan_name, "Silver")
        up = LeadUpdate.objects.get(lead=self.lead, type=LeadUpdateTypes.SUBSCRIPTION)
        self.assertEqual(up.to_value, "updated")

    def test_permission(self):
        with self.assertRaises(PermissionDenied):
            svc.update_subscription(self.a, self.sub, {"plan_name": "Silver"})

    def test_total_below_paid_overpaid(self):
        make_payment(self.sub, "600", TODAY)
        self.assertEqual(self.code(svc.update_subscription, self.leader, self.sub, {"total_amount": "500"}), "overpaid")
        svc.update_subscription(self.leader, self.sub, {"total_amount": "600"})

    def test_closed_period_freezes_fields(self):
        old = D(2026, 1, 10)
        make_payment(self.sub, "100", old)
        self.close_period(old)
        self.assertEqual(self.code(svc.update_subscription, self.leader, self.sub, {"currency": "USD"}), "period_closed")
        sub = svc.update_subscription(self.leader, self.sub, {"plan_name": "Renamed", "currency": "SAR"})
        self.assertEqual(sub.plan_name, "Renamed")

    def test_seller_unchanged_while_no_longer_assigned(self):
        # Review Focus 2
        sub = make_subscription(self.lead, self.b)
        sub = svc.update_subscription(self.leader, sub, {"seller": str(self.b.pk), "plan_name": "Z"})
        self.assertEqual(sub.seller, self.b)
        sub = svc.update_subscription(self.leader, sub, {"seller": str(self.c.pk)})
        self.assertEqual(sub.seller, self.c)

    def test_seller_change_to_non_assignee_invalid(self):
        self.assertEqual(self.code(svc.update_subscription, self.leader, self.sub, {"seller": str(self.b.pk)}), "invalid")

    def test_cancelled_refused(self):
        svc.cancel_subscription(self.leader, self.sub, "r")
        self.assertEqual(self.code(svc.update_subscription, self.leader, self.sub, {"plan_name": "Q"}), "cancelled")

    def test_dates_validated_merged(self):
        self.assertEqual(self.code(
            svc.update_subscription, self.leader, self.sub,
            {"end_date": (TODAY - dt.timedelta(days=1)).isoformat()}), "invalid")


class CancelDeleteTests(ServiceBase):
    def setUp(self):
        super().setUp()
        self.sub = make_subscription(self.lead, self.a)

    def test_cancel(self):
        make_payment(self.sub, "100", TODAY)
        sub = svc.cancel_subscription(self.leader, self.sub, " too pricey ")
        self.assertIsNotNone(sub.cancelled_at)
        self.assertEqual(sub.cancelled_by, self.leader)
        self.assertEqual(sub.cancel_reason, "too pricey")
        self.assertEqual(sub.payments.count(), 1)
        up = LeadUpdate.objects.get(lead=self.lead, type=LeadUpdateTypes.SUBSCRIPTION)
        self.assertEqual((up.to_value, up.note), ("cancelled", "too pricey"))

    def test_cancel_invalid_reason_and_twice(self):
        for bad in ("", "   ", None, "x" * 301):
            self.assertEqual(self.code(svc.cancel_subscription, self.leader, self.sub, bad), "invalid")
        svc.cancel_subscription(self.leader, self.sub, "r")
        self.assertEqual(self.code(svc.cancel_subscription, self.leader, self.sub, "r"), "cancelled")

    def test_cancel_permission(self):
        with self.assertRaises(PermissionDenied):
            svc.cancel_subscription(self.a, self.sub, "r")

    def test_delete_with_payments(self):
        make_payment(self.sub, "100", TODAY)
        self.assertEqual(self.code(svc.delete_subscription, self.leader, self.sub), "has_payments")
        self.assertTrue(Subscription.objects.filter(pk=self.sub.pk).exists())

    def test_delete_without(self):
        svc.delete_subscription(self.leader, self.sub)
        self.assertFalse(Subscription.objects.filter(pk=self.sub.pk).exists())
        up = LeadUpdate.objects.get(lead=self.lead, type=LeadUpdateTypes.SUBSCRIPTION)
        self.assertEqual(up.to_value, "deleted: Gold")

    def test_delete_permission(self):
        with self.assertRaises(PermissionDenied):
            svc.delete_subscription(self.a, self.sub)


class PaymentTests(ServiceBase):
    def setUp(self):
        super().setUp()
        self.sub = make_subscription(self.lead, self.a, total_amount=Decimal("1000"))

    def pay(self, **kw):
        data = {"amount": "100", "paid_on": TODAY.isoformat(), "method": "cash"}
        data.update(kw)
        return {k: v for k, v in data.items() if v is not ...}

    def test_add_ok_and_log(self):
        p = svc.add_payment(self.a, self.sub, self.pay(amount="600.5", transaction_id="T1", note="n"))
        self.assertEqual(p.amount, Decimal("600.50"))
        self.assertEqual(p.recorded_by, self.a)
        self.assertEqual(svc.paid_amount(self.sub), Decimal("600.50"))
        up = LeadUpdate.objects.get(lead=self.lead, type=LeadUpdateTypes.PAYMENT)
        self.assertEqual(up.to_value, f"payment: 600.50 SAR on {TODAY}")

    def test_seller_without_active_assignment_may_add(self):
        sub = make_subscription(self.lead, self.past)
        svc.add_payment(self.past, sub, self.pay())

    def test_add_permission(self):
        with self.assertRaises(PermissionDenied):
            svc.add_payment(self.b, self.sub, self.pay())

    def test_future_date(self):
        tomorrow = (TODAY + dt.timedelta(days=1)).isoformat()
        self.assertEqual(self.code(svc.add_payment, self.a, self.sub, self.pay(paid_on=tomorrow)), "future_date")

    def test_overpaid_second_rejected(self):
        # Review Focus 1
        svc.add_payment(self.a, self.sub, self.pay(amount="600"))
        self.assertEqual(self.code(svc.add_payment, self.a, self.sub, self.pay(amount="500")), "overpaid")
        svc.add_payment(self.a, self.sub, self.pay(amount="400"))
        self.assertEqual(self.sub.payments.count(), 2)

    def test_overpaid_uses_fresh_total_not_stale_instance(self):
        svc.add_payment(self.a, self.sub, self.pay(amount="600"))
        stale = Subscription.objects.get(pk=self.sub.pk)
        make_payment(self.sub, "300", TODAY)  # concurrent writer
        self.assertEqual(self.code(svc.add_payment, self.a, stale, self.pay(amount="200")), "overpaid")

    def test_cancelled(self):
        svc.cancel_subscription(self.leader, self.sub, "r")
        self.assertEqual(self.code(svc.add_payment, self.a, self.sub, self.pay()), "cancelled")

    def test_closed_period(self):
        d = D(2026, 1, 10)
        self.close_period(d)
        self.assertEqual(self.code(svc.add_payment, self.a, self.sub, self.pay(paid_on=d.isoformat())), "period_closed")

    def test_invalid_fields(self):
        for kw in ({"amount": "1,000"}, {"amount": None}, {"method": "x"}, {"method": ...},
                   {"paid_on": ...}, {"paid_on": "nope"}, {"transaction_id": "x" * 101}, {"note": "x" * 501}):
            self.assertEqual(self.code(svc.add_payment, self.a, self.sub, self.pay(**kw)), "invalid", kw)

    def test_update_payment(self):
        p = make_payment(self.sub, "300", TODAY, recorded_by=self.a)
        p = svc.update_payment(self.a, p, {"amount": "400"})
        self.assertEqual(p.amount, Decimal("400.00"))
        up = LeadUpdate.objects.get(lead=self.lead, type=LeadUpdateTypes.PAYMENT)
        self.assertEqual(up.to_value, f"payment updated: 400.00 SAR on {TODAY}")

    def test_update_payment_overpaid_excludes_self(self):
        p = make_payment(self.sub, "600", TODAY, recorded_by=self.a)
        make_payment(self.sub, "300", TODAY)
        svc.update_payment(self.a, p, {"amount": "700"})
        self.assertEqual(self.code(svc.update_payment, self.a, p, {"amount": "701"}), "overpaid")

    def test_update_permission(self):
        p = make_payment(self.sub, "300", TODAY, recorded_by=self.c)
        with self.assertRaises(PermissionDenied):
            svc.update_payment(self.a, p, {"amount": "10"})
        svc.update_payment(self.leader, p, {"amount": "10"})

    def test_update_move_into_closed(self):
        d = D(2026, 1, 10)
        self.close_period(d)
        p = make_payment(self.sub, "300", TODAY, recorded_by=self.a)
        self.assertEqual(self.code(svc.update_payment, self.a, p, {"paid_on": d.isoformat()}), "period_closed")

    def test_existing_in_closed_period(self):
        d = D(2026, 1, 10)
        p = make_payment(self.sub, "300", d, recorded_by=self.a)
        self.close_period(d)
        self.assertEqual(self.code(svc.update_payment, self.a, p, {"amount": "10"}), "period_closed")
        self.assertEqual(self.code(svc.delete_payment, self.a, p), "period_closed")

    def test_update_future_date(self):
        p = make_payment(self.sub, "300", TODAY, recorded_by=self.a)
        tomorrow = (TODAY + dt.timedelta(days=1)).isoformat()
        self.assertEqual(self.code(svc.update_payment, self.a, p, {"paid_on": tomorrow}), "future_date")

    def test_delete_payment(self):
        p = make_payment(self.sub, "300", TODAY, recorded_by=self.a)
        svc.delete_payment(self.a, p)
        self.assertFalse(Payment.objects.filter(pk=p.pk).exists())
        up = LeadUpdate.objects.get(lead=self.lead, type=LeadUpdateTypes.PAYMENT)
        self.assertEqual(up.to_value, f"payment deleted: 300.00 SAR on {TODAY}")

    def test_delete_permission(self):
        p = make_payment(self.sub, "300", TODAY, recorded_by=self.c)
        with self.assertRaises(PermissionDenied):
            svc.delete_payment(self.a, p)
