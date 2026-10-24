from rest_framework import serializers

from apps.attendance.models import AttendanceDay, Punch
from apps.users.models import User

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

    class Meta:
        model = AttendanceDay
        fields = ["uuid", "user", "date", "status", "first_in", "last_out", "worked_minutes",
                  "late_minutes", "early_leave_minutes", "deduction_days", "late_excused_by_allowance",
                  "shift_name", "expected_start", "expected_end", "grace_minutes", "is_working_day",
                  "evaluated_at"]


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
