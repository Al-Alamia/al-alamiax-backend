import datetime as dt
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import PermissionDenied

from apps.attendance.models import AttendanceDay, Punch, Request
from apps.attendance.services import requests as svc
from apps.attendance.services.requests import RequestError
from apps.attendance.tests.factories import assign, make_leave_type, make_policy, make_request, make_shift
from apps.attendance.types import DayStatus, PunchSource, RequestKind as K, RequestStatus as S
from apps.notifications.models import NotificationRecipient
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = dt.date
NOW = dt.datetime(2026, 10, 25, 12)  # Sunday


class RequestServiceBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(svc, "_now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        make_policy()
        assign(make_shift(weekend_days=[4, 5]), department=self.department)  # Fri, Sat off
        self.other_dept = Department.objects.create(name="Other")
        self.manager = self.mkuser("manager", UserTypes.MANAGER)
        self.hr = self.mkuser("hr", UserTypes.HR)
        self.outsider = self.mkuser("outsider", UserTypes.AGENT, self.other_dept)
        assign(make_shift(), department=self.other_dept)
        self.annual = make_leave_type(name="Annual", uses_balance=True, yearly_allowance=21)
        self.sick = make_leave_type(name="Sick", requires_attachment=True)

    def mkuser(self, name, role, dept=None):
        u = User.objects.create_user(username=name, password="x", email=f"{name}@t.com", role=role,
                                     project=self.project, department=dept or self.department)
        User.objects.filter(pk=u.pk).update(date_joined=dt.datetime(2020, 1, 1))
        u.refresh_from_db()
        return u

    def leave(self, start=D(2026, 11, 2), end=None, actor=None, **kw):
        data = {"kind": K.LEAVE, "start_date": start, "end_date": end or start,
                "leave_type": self.annual}
        data.update(kw)
        return svc.submit(actor or self.agent, data)

    def notified(self, user):
        return NotificationRecipient.objects.filter(user=user).count()

    def code(self, fn, *a, **kw):
        with self.assertRaises(RequestError) as cm:
            fn(*a, **kw)
        return cm.exception.type

    def file(self, name="a.pdf", size=10, ctype="application/pdf"):
        f = SimpleUploadedFile(name, b"x" * size, content_type=ctype)
        return f


class ValidationTests(RequestServiceBase):
    def test_rejects_fields_of_other_kind(self):
        self.assertEqual(self.code(self.leave, minutes=10), "validation")

    def test_required_fields(self):
        sub = lambda **d: svc.submit(self.agent, d)  # noqa: E731
        d = D(2026, 11, 2)
        self.assertEqual(self.code(sub, kind=K.LATE_EXCUSE, start_date=d), "validation")
        self.assertEqual(self.code(sub, kind=K.GENERAL, start_date=d), "validation")
        self.assertEqual(self.code(sub, kind=K.MISSED_PUNCH, start_date=d), "validation")
        self.assertEqual(self.code(sub, kind="NOPE", start_date=d), "validation")
        self.assertEqual(self.code(sub, kind=K.LEAVE, start_date=d), "validation")  # no leave_type
        self.assertEqual(self.code(self.leave, end=D(2026, 11, 1), start=d), "validation")

    def test_single_day_kinds(self):
        code = self.code(svc.submit, self.agent, {
            "kind": K.LATE_EXCUSE, "start_date": D(2026, 11, 2), "end_date": D(2026, 11, 3),
            "minutes": 15})
        self.assertEqual(code, "validation")

    def test_crosses_year(self):
        self.assertEqual(self.code(self.leave, D(2026, 12, 30), D(2027, 1, 2)), "crosses_year")

    def test_overlap_same_kind(self):
        self.leave(D(2026, 11, 2), D(2026, 11, 4))
        self.assertEqual(self.code(self.leave, D(2026, 11, 4), D(2026, 11, 5)), "overlap")
        self.leave(D(2026, 11, 5), D(2026, 11, 5))  # adjacent is fine

    def test_overlap_leave_any_type(self):
        self.leave(D(2026, 11, 2), D(2026, 11, 4))
        self.assertEqual(self.code(self.leave, D(2026, 11, 3), leave_type=make_leave_type()), "overlap")

    def test_overlap_ignores_rejected_and_other_kind(self):
        make_request(self.agent, K.LEAVE, D(2026, 11, 2), status=S.REJECTED, leave_type=self.annual)
        self.leave(D(2026, 11, 2))
        svc.submit(self.agent, {"kind": K.LATE_EXCUSE, "start_date": D(2026, 11, 2), "minutes": 5})

    def test_inactive_type(self):
        self.annual.is_active = False
        self.annual.save()
        self.assertEqual(self.code(self.leave), "validation")

    def test_attachment_required(self):
        self.assertEqual(self.code(self.leave, leave_type=self.sick), "attachment_required")
        req = svc.submit(self.agent, {"kind": K.LEAVE, "start_date": D(2026, 11, 2),
                                      "leave_type": self.sick}, self.file())
        self.assertTrue(req.attachment)

    def test_attachment_type_and_size(self):
        bad = lambda f: self.code(svc.submit, self.agent, {  # noqa: E731
            "kind": K.GENERAL, "start_date": D(2026, 11, 2), "details": "x"}, f)
        self.assertEqual(bad(self.file("a.exe", ctype="application/octet-stream")), "validation")
        self.assertEqual(bad(self.file("a.pdf", size=5 * 1024 * 1024 + 1)), "validation")
        svc.submit(self.agent, {"kind": K.GENERAL, "start_date": D(2026, 11, 2), "details": "x"},
                   self.file("a.PNG", ctype="image/png"))

    def test_insufficient_balance_on_submit(self):
        self.assertEqual(self.code(self.leave, D(2026, 11, 1), D(2026, 12, 3)), "insufficient_balance")
        self.leave(D(2026, 11, 1), D(2026, 11, 29))  # exactly 21 working days: allowed

    def test_no_working_days(self):
        self.assertEqual(self.code(self.leave, D(2026, 11, 6), D(2026, 11, 7)), "no_working_days")

    def test_missed_punch_future_time(self):
        self.assertEqual(self.code(svc.submit, self.agent, {
            "kind": K.MISSED_PUNCH, "start_date": D(2026, 10, 26),
            "punch_time": dt.datetime(2026, 10, 26, 9)}), "validation")

    def test_missed_punch_time_must_match_date(self):
        self.assertEqual(self.code(svc.submit, self.agent, {
            "kind": K.MISSED_PUNCH, "start_date": D(2026, 10, 20),
            "punch_time": dt.datetime(2026, 10, 21, 9)}), "validation")

    def test_cancellation_validation_and_duplicate(self):
        orig = make_request(self.agent, K.LEAVE, D(2026, 10, 20), leave_type=self.annual)
        cr = svc.submit(self.agent, {"kind": K.CANCELLATION, "cancels": orig})
        self.assertEqual((cr.start_date, cr.end_date, cr.status), (D(2026, 10, 20), D(2026, 10, 20), S.PENDING))
        self.assertEqual(self.code(svc.submit, self.agent, {"kind": K.CANCELLATION, "cancels": orig}),
                         "overlap")
        future = make_request(self.agent, K.LEAVE, D(2026, 11, 2), leave_type=self.annual)
        self.assertEqual(self.code(svc.submit, self.agent, {"kind": K.CANCELLATION, "cancels": future}),
                         "invalid_state")
        with self.assertRaises(PermissionDenied):
            svc.submit(self.manager, {"kind": K.CANCELLATION, "cancels": orig, "user": self.agent})

    def test_missed_punch_and_general_exempt_from_overlap(self):
        d = D(2026, 10, 20)
        for h in (9, 17):
            svc.submit(self.agent, {"kind": K.MISSED_PUNCH, "start_date": d,
                                    "punch_time": dt.datetime(2026, 10, 20, h)})
        for _ in range(2):
            svc.submit(self.agent, {"kind": K.GENERAL, "start_date": d, "details": "x"})
        svc.submit(self.agent, {"kind": K.LATE_EXCUSE, "start_date": d, "minutes": 5})
        self.assertEqual(self.code(svc.submit, self.agent, {
            "kind": K.LATE_EXCUSE, "start_date": d, "minutes": 7}), "overlap")

    def test_missed_punch_recalculates_padded_range(self):
        req = svc.submit(self.agent, {"kind": K.MISSED_PUNCH, "start_date": D(2026, 10, 20),
                                      "punch_time": dt.datetime(2026, 10, 20, 9)})
        with mock.patch.object(svc, "recalculate") as m:
            svc.approve(self.manager, req)
        self.assertEqual(m.call_args[0][:2], (D(2026, 10, 19), D(2026, 10, 21)))

    def test_edit_excludes_self_from_overlap_and_balance(self):
        req = self.leave(D(2026, 11, 1), D(2026, 11, 26))  # 20 of 21
        edited = svc.edit(self.agent, req, {"end_date": D(2026, 11, 29)})  # 21
        self.assertEqual(edited.end_date, D(2026, 11, 29))
        self.assertEqual(self.code(svc.edit, self.agent, req, {"leave_type": self.sick}),
                         "attachment_required")

    def test_edit_moves_single_day_request_to_another_date(self):
        req = svc.submit(self.agent, {"kind": K.LATE_EXCUSE, "start_date": D(2026, 11, 2), "minutes": 10})
        edited = svc.edit(self.agent, req, {"start_date": D(2026, 11, 3)})
        self.assertEqual((edited.start_date, edited.end_date), (D(2026, 11, 3), D(2026, 11, 3)))
        gen = svc.submit(self.agent, {"kind": K.GENERAL, "start_date": D(2026, 11, 2), "details": "x"})
        edited = svc.edit(self.agent, gen, {"start_date": D(2026, 11, 4)})
        self.assertEqual(edited.end_date, D(2026, 11, 4))

    def test_edit_permissions_and_state(self):
        req = self.leave()
        with self.assertRaises(PermissionDenied):
            svc.edit(self.outsider, req, {"end_date": D(2026, 11, 3)})
        svc.reject(self.manager, req)
        self.assertEqual(self.code(svc.edit, self.agent, req, {"end_date": D(2026, 11, 3)}),
                         "invalid_state")


class LifecycleTests(RequestServiceBase):
    def test_approve_leave_sets_days_and_notifies(self):
        req = self.leave(D(2026, 11, 2), D(2026, 11, 4))
        req = svc.approve(self.manager, req, note="ok")
        self.assertEqual(req.status, S.APPROVED)
        self.assertEqual(req.decided_by, self.manager)
        self.assertEqual(req.decision_note, "ok")
        self.assertEqual(req.leave_days, Decimal("3"))
        self.assertEqual(AttendanceDay.objects.filter(user=self.agent, status=DayStatus.LEAVE).count(), 3)
        self.assertEqual(self.notified(self.agent), 1)
        self.assertEqual(self.notified(self.manager), 1)  # submit notice only

    def test_approve_requires_scope(self):
        req = self.leave()
        with self.assertRaises(PermissionDenied):
            svc.approve(self.outsider, req)
        with self.assertRaises(PermissionDenied):
            svc.approve(self.agent, req)

    def test_approve_rechecks_balance(self):
        a = self.leave(D(2026, 11, 1), D(2026, 11, 16))  # 12 working days
        b = self.leave(D(2026, 11, 17), D(2026, 12, 2), actor=self.agent)  # 12 working days
        svc.approve(self.manager, a)
        self.assertEqual(self.code(svc.approve, self.manager, b), "insufficient_balance")
        b = svc.approve(self.hr, b, over_balance=True)
        self.assertTrue(b.over_balance)
        self.assertEqual(b.status, S.APPROVED)

    def test_over_balance_flag_not_set_when_it_fits(self):
        req = svc.approve(self.hr, self.leave(), over_balance=True)
        self.assertFalse(req.over_balance)

    def test_over_balance_hr_only(self):
        with self.assertRaises(PermissionDenied):
            svc.approve(self.manager, self.leave(), over_balance=True)

    def test_double_approve_invalid_state(self):
        req = svc.submit(self.agent, {"kind": K.MISSED_PUNCH, "start_date": D(2026, 10, 20),
                                      "punch_time": dt.datetime(2026, 10, 20, 9), "details": "forgot"})
        svc.approve(self.manager, req)
        self.assertEqual(self.code(svc.approve, self.manager, req), "invalid_state")
        self.assertEqual(Punch.objects.filter(source=PunchSource.REQUEST).count(), 1)

    def test_missed_punch_approve_and_revoke(self):
        Punch.objects.create(user=self.agent, timestamp=dt.datetime(2026, 10, 20, 17), source=PunchSource.WEB)
        req = svc.submit(self.agent, {"kind": K.MISSED_PUNCH, "start_date": D(2026, 10, 20),
                                      "punch_time": dt.datetime(2026, 10, 20, 9), "details": "forgot"})
        svc.approve(self.manager, req)
        req.refresh_from_db()
        self.assertEqual(req.punch.source, PunchSource.REQUEST)
        self.assertEqual(req.punch.created_by, self.manager)
        self.assertEqual(req.punch.note, "forgot")
        day = AttendanceDay.objects.get(user=self.agent, date=D(2026, 10, 20))
        self.assertNotEqual(day.status, DayStatus.INCOMPLETE)
        svc.revoke(self.hr, req, "wrong")
        self.assertFalse(Punch.objects.filter(source=PunchSource.REQUEST).exists())
        day.refresh_from_db()
        self.assertEqual(day.status, DayStatus.INCOMPLETE)

    def test_reject(self):
        req = svc.reject(self.manager, self.leave(), "no")
        self.assertEqual((req.status, req.decided_by, req.decision_note), (S.REJECTED, self.manager, "no"))
        self.assertEqual(self.notified(self.agent), 1)
        self.assertEqual(self.code(svc.reject, self.manager, req), "invalid_state")

    def test_cancel_pending(self):
        req = svc.cancel(self.agent, self.leave())
        self.assertEqual(req.status, S.CANCELLED)
        with self.assertRaises(PermissionDenied):
            svc.cancel(self.outsider, self.leave())

    def test_cancel_future_approved_restores_balance(self):
        req = svc.approve(self.manager, self.leave(D(2026, 11, 2), D(2026, 11, 4)))
        from apps.attendance.services import leave as lv
        self.assertEqual(lv.remaining(self.agent, self.annual, 2026), Decimal("18"))
        svc.cancel(self.agent, req)
        self.assertEqual(lv.remaining(self.agent, self.annual, 2026), Decimal("21"))
        self.assertFalse(AttendanceDay.objects.filter(user=self.agent, status=DayStatus.LEAVE).exists())

    def test_cancel_started_approved_invalid_state(self):
        req = make_request(self.agent, K.LEAVE, D(2026, 10, 25), leave_type=self.annual)
        self.assertEqual(self.code(svc.cancel, self.agent, req), "invalid_state")

    def test_cancellation_request_flow(self):
        orig = make_request(self.agent, K.LEAVE, D(2026, 10, 20), D(2026, 10, 22), leave_type=self.annual)
        svc.recalculate(D(2026, 10, 20), D(2026, 10, 22), [self.agent], NOW)
        cr = svc.submit(self.agent, {"kind": K.CANCELLATION, "cancels": orig})
        svc.reject(self.manager, cr)
        orig.refresh_from_db()
        self.assertEqual(orig.status, S.APPROVED)
        cr2 = svc.submit(self.agent, {"kind": K.CANCELLATION, "cancels": orig})
        cr2 = svc.approve(self.manager, cr2)
        orig.refresh_from_db()
        self.assertEqual((cr2.status, orig.status), (S.APPROVED, S.CANCELLED))
        days = AttendanceDay.objects.filter(user=self.agent, date__range=(D(2026, 10, 20), D(2026, 10, 22)))
        self.assertEqual({d.status for d in days}, {DayStatus.ABSENT})

    def test_revoke_requires_note(self):
        req = svc.approve(self.manager, self.leave())
        self.assertEqual(self.code(svc.revoke, self.hr, req, " "), "validation")
        with self.assertRaises(PermissionDenied):
            svc.revoke(self.manager, req, "x")
        req = svc.revoke(self.hr, req, "mistake")
        self.assertEqual((req.status, req.decision_note, req.decided_by), (S.REVOKED, "mistake", self.hr))
        self.assertEqual(self.code(svc.revoke, self.hr, req, "again"), "invalid_state")

    def test_revoke_cancellation_invalid(self):
        cr = make_request(self.agent, K.CANCELLATION, D(2026, 10, 20))
        self.assertEqual(self.code(svc.revoke, self.hr, cr, "x"), "invalid_state")


class NoticeTests(RequestServiceBase):
    def test_submit_notifies_manager_else_hr(self):
        self.leave()
        self.assertEqual((self.notified(self.manager), self.notified(self.hr)), (1, 0))
        n = NotificationRecipient.objects.get(user=self.manager).notification
        self.assertEqual((n.kind, n.sender), ("request", self.agent))
        self.assertTrue(n.link.startswith("/attendance/approvals?request="))
        self.leave(actor=self.manager, start=D(2026, 11, 9))
        self.assertEqual(self.notified(self.hr), 1)  # manager's own request -> HR
        self.leave(actor=self.outsider, start=D(2026, 11, 16))  # no manager in that department
        self.assertEqual(self.notified(self.hr), 2)

    def test_on_behalf_sets_created_by_and_notifies_both(self):
        req = self.leave(actor=self.hr, user=self.agent)
        self.assertEqual((req.user, req.created_by), (self.agent, self.hr))
        self.assertEqual((self.notified(self.agent), self.notified(self.manager)), (1, 1))
        self.assertEqual(self.notified(self.hr), 0)
        with self.assertRaises(PermissionDenied):
            self.leave(actor=self.outsider, user=self.agent, start=D(2026, 11, 9))

    def test_decision_notifies_requester_and_filer_not_actor(self):
        req = self.leave(actor=self.hr, user=self.agent)
        before = self.notified(self.hr)
        svc.approve(self.manager, req)
        self.assertEqual(self.notified(self.hr), before + 1)
        self.assertEqual(self.notified(self.manager), 1)
        n = NotificationRecipient.objects.filter(user=self.hr).last().notification
        self.assertTrue(n.link.startswith("/attendance/requests?request="))

    def test_no_notice_when_no_recipients(self):
        User.objects.filter(pk=self.manager.pk).update(is_active=False)
        svc.submit(self.hr, {"kind": K.GENERAL, "start_date": D(2026, 11, 2), "details": "x"})
        self.assertEqual(NotificationRecipient.objects.count(), 0)  # the only HR user is the actor
