from typing import Optional

from rest_framework import serializers

from apps.attendance.models import (AttendanceDay, AttendanceSettings, DeductionPolicy, Holiday, Punch,
                                    Request, Shift, ShiftAssignment, WebPunchPolicy)
from apps.attendance.permissions import request_can
from apps.users.models import Department, User, ZKConfig

DT_FORMAT = "%Y-%m-%dT%H:%M:%S"


class UserRefSerializer(serializers.ModelSerializer):
    department = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["uuid", "username", "first_name", "last_name", "department"]

    def get_department(self, user):
        d = user.department
        return {"uuid": str(d.uuid), "name": d.name} if d else None


class AttendanceDaySerializer(serializers.ModelSerializer):
    user = UserRefSerializer(read_only=True)
    first_in = serializers.DateTimeField(format=DT_FORMAT)
    last_out = serializers.DateTimeField(format=DT_FORMAT)
    expected_start = serializers.DateTimeField(format=DT_FORMAT)
    expected_end = serializers.DateTimeField(format=DT_FORMAT)
    evaluated_at = serializers.DateTimeField(format=DT_FORMAT)
    request = serializers.UUIDField(source="request_id", read_only=True, allow_null=True)

    class Meta:
        model = AttendanceDay
        fields = ["uuid", "user", "date", "status", "first_in", "last_out", "worked_minutes",
                  "late_minutes", "early_leave_minutes", "deduction_days", "late_excused_by_allowance",
                  "shift_name", "expected_start", "expected_end", "grace_minutes", "is_working_day",
                  "evaluated_at", "excused_late_minutes", "excused_early_minutes", "request"]


class PunchSerializer(serializers.ModelSerializer):
    user = serializers.UUIDField(source="user_id")
    timestamp = serializers.DateTimeField(format=DT_FORMAT)
    device_id = serializers.CharField(source="browser_id")
    device_name = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = Punch
        fields = ["uuid", "user", "timestamp", "source", "ip", "device_id", "device_name",
                  "created_by", "note"]

    def get_device_name(self, punch):
        return (punch.device.name or punch.device.ip) if punch.device else None

    def get_created_by(self, punch):
        return punch.created_by.username if punch.created_by else None


def _hhmm(t) -> str:
    return t.strftime("%H:%M")


def _dept_name(obj):
    return obj.department.name if obj.department_id else None


def _dept_uuid(obj):
    return str(obj.department_id) if obj.department_id else None


def shift_data(s: Shift) -> dict:
    return {"uuid": str(s.uuid), "name": s.name, "start_time": _hhmm(s.start_time),
            "end_time": _hhmm(s.end_time), "weekend_days": s.weekend_days,
            "grace_minutes": s.grace_minutes, "active": s.active,
            "crosses_midnight": s.crosses_midnight}


def assignment_data(a: ShiftAssignment) -> dict:
    return {"uuid": str(a.uuid), "shift": str(a.shift_id), "shift_name": a.shift.name,
            "department": _dept_uuid(a), "department_name": _dept_name(a),
            "user": str(a.user_id) if a.user_id else None,
            "username": a.user.username if a.user_id else None,
            "effective_from": a.effective_from.isoformat()}


def holiday_data(h: Holiday) -> dict:
    return {"uuid": str(h.uuid), "date": h.date.isoformat(), "name": h.name,
            "department": _dept_uuid(h), "department_name": _dept_name(h)}


def policy_data(p: DeductionPolicy) -> dict:
    tiers = sorted(p.tiers.all(), key=lambda t: (t.kind, t.min_minutes))
    return {"uuid": str(p.uuid), "department": _dept_uuid(p), "department_name": _dept_name(p),
            "monthly_late_allowance": p.monthly_late_allowance, "absence_days": p.absence_days,
            "tiers": [{"kind": t.kind, "min_minutes": t.min_minutes, "deduction_days": t.deduction_days}
                      for t in tiers]}


def web_punch_policy_data(department: Department, policy: Optional[WebPunchPolicy]) -> dict:
    return {"department": str(department.uuid), "department_name": department.name,
            "require_trusted_device": policy.require_trusted_device if policy else False,
            "require_office_ip": policy.require_office_ip if policy else False,
            "allowed_ips": list(policy.allowed_ips) if policy else []}


def settings_data(s: AttendanceSettings) -> dict:
    return {"period_start_day": s.period_start_day, "device_sync_minutes": s.device_sync_minutes,
            "last_nightly_run": s.last_nightly_run.isoformat() if s.last_nightly_run else None}


def device_data(z: ZKConfig) -> dict:
    return {"uuid": str(z.uuid), "name": z.name, "ip": z.ip, "port": z.port,
            "last_synced_at": z.last_synced_at.strftime(DT_FORMAT) if z.last_synced_at else None}


def _name_ref(user) -> Optional[dict]:
    if user is None:
        return None
    return {"uuid": str(user.uuid), "name": user.get_full_name().strip() or user.username}


class RequestSerializer(serializers.ModelSerializer):
    """Context: ``viewer`` and ``today`` (for ``can``); ``request`` for absolute attachment URLs;
    ``with_days`` adds the affected attendance days."""
    user = UserRefSerializer(read_only=True)
    created_by = serializers.SerializerMethodField()
    leave_type = serializers.SerializerMethodField()
    punch_time = serializers.DateTimeField(format=DT_FORMAT)
    cancels = serializers.UUIDField(source="cancels_id", read_only=True, allow_null=True)
    attachment = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    decided_at = serializers.DateTimeField(format=DT_FORMAT)
    created_at = serializers.DateTimeField(format=DT_FORMAT)
    leave_days = serializers.SerializerMethodField()
    can = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = ["uuid", "kind", "status", "user", "created_by", "start_date", "end_date", "leave_type",
                  "minutes", "punch_time", "cancels", "details", "attachment", "decided_by", "decided_at",
                  "decision_note", "over_balance", "leave_days", "created_at", "can"]

    def get_created_by(self, req):
        return _name_ref(req.created_by)

    def get_decided_by(self, req):
        return _name_ref(req.decided_by)

    def get_leave_type(self, req):
        lt = req.leave_type
        return {"uuid": str(lt.uuid), "name": lt.name, "pay_percent": lt.pay_percent} if lt else None

    def get_attachment(self, req):
        if not req.attachment:
            return None
        http = self.context.get("request")
        return http.build_absolute_uri(req.attachment.url) if http else req.attachment.url

    def get_leave_days(self, req):
        return float(req.leave_days)

    def get_can(self, req):
        return request_can(self.context["viewer"], req, self.context["today"])

    def to_representation(self, req):
        data = super().to_representation(req)
        if self.context.get("with_days"):
            days = req.attendance_days.order_by("date")
            data["days"] = [{"date": d.date.isoformat(), "status": d.status} for d in days]
        return data
