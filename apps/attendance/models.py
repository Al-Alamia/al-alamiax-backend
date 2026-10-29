from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import BaseModel
from apps.users.models import Department, User, ZKConfig
from .types import DayStatus, PunchSource, RequestKind, RequestStatus, TierKind


class AttendanceSettings(models.Model):
    """Singleton row (pk=1); use ``AttendanceSettings.get()``."""
    period_start_day = models.PositiveSmallIntegerField(
        default=26, validators=[MinValueValidator(1), MaxValueValidator(28)])
    device_sync_minutes = models.PositiveIntegerField(default=60)
    sync_started_at = models.DateTimeField(null=True, blank=True)
    last_nightly_run = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Attendance Settings"
        verbose_name_plural = "Attendance Settings"

    @classmethod
    def get(cls) -> "AttendanceSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Attendance Settings"


class Shift(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    # Python weekday(): 0=Mon ... 6=Sun
    weekend_days = models.JSONField(default=list, blank=True)
    grace_minutes = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    @property
    def crosses_midnight(self) -> bool:
        return self.end_time <= self.start_time

    def __str__(self):
        return self.name


class ShiftAssignment(BaseModel):
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="assignments")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name="shift_assignments")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True,
                             related_name="shift_assignments")
    effective_from = models.DateField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(Q(department__isnull=False, user__isnull=True)
                       | Q(department__isnull=True, user__isnull=False)),
                name="shiftassignment_department_xor_user"),
            models.UniqueConstraint(fields=["department", "effective_from"],
                                    name="shiftassignment_unique_department_date"),
            models.UniqueConstraint(fields=["user", "effective_from"],
                                    name="shiftassignment_unique_user_date"),
        ]


class Holiday(BaseModel):
    date = models.DateField()
    name = models.CharField(max_length=150)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name="holidays")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["date", "department"], name="holiday_unique_date_department"),
            # NULLs are distinct in unique indexes, so global holidays need their own constraint
            models.UniqueConstraint(fields=["date"], condition=Q(department__isnull=True),
                                    name="holiday_unique_global_date"),
        ]

    def __str__(self):
        return f"{self.date} {self.name}"


class DeductionPolicy(BaseModel):
    department = models.OneToOneField(Department, on_delete=models.CASCADE, null=True, blank=True,
                                      related_name="deduction_policy")
    monthly_late_allowance = models.PositiveIntegerField(default=0)
    absence_days = models.FloatField(default=1.0)
    # True exactly when department is NULL; lets a conditional unique index allow a single global row
    is_global = models.BooleanField(default=False, editable=False)

    class Meta:
        verbose_name_plural = "Deduction policies"
        constraints = [
            models.UniqueConstraint(fields=["is_global"], condition=Q(is_global=True),
                                    name="deductionpolicy_single_global"),
        ]

    def save(self, *args, **kwargs):
        self.is_global = self.department_id is None
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"is_global"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Policy {self.department or 'global'}"


class DeductionTier(BaseModel):
    policy = models.ForeignKey(DeductionPolicy, on_delete=models.CASCADE, related_name="tiers")
    kind = models.CharField(max_length=20, choices=TierKind.choices)
    min_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    deduction_days = models.FloatField(validators=[MinValueValidator(0)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["policy", "kind", "min_minutes"],
                                    name="deductiontier_unique_policy_kind_min"),
            models.CheckConstraint(check=Q(min_minutes__gte=1), name="deductiontier_min_minutes_gte_1"),
            models.CheckConstraint(check=Q(deduction_days__gte=0), name="deductiontier_deduction_days_gte_0"),
        ]


class Punch(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="punches")
    timestamp = models.DateTimeField()
    source = models.CharField(max_length=10, choices=PunchSource.choices)
    ip = models.GenericIPAddressField(null=True, blank=True)
    # browser FingerPrintID.unique_id (named browser_id: "device_id" would clash with the `device` FK attname)
    browser_id = models.CharField(max_length=100, blank=True)
    device = models.ForeignKey(ZKConfig, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="punches")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="punches_created")
    note = models.CharField(max_length=255, blank=True)
    is_demo = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "user", "timestamp"],
                                    condition=Q(device__isnull=False),
                                    name="punch_unique_device_user_timestamp"),
        ]
        indexes = [models.Index(fields=["user", "timestamp"], name="punch_user_timestamp_idx")]


class AttendanceDay(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendance_days")
    date = models.DateField()
    status = models.CharField(max_length=12, choices=DayStatus.choices)
    first_in = models.DateTimeField(null=True, blank=True)
    last_out = models.DateTimeField(null=True, blank=True)
    worked_minutes = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    early_leave_minutes = models.PositiveIntegerField(default=0)
    deduction_days = models.FloatField(default=0)
    late_excused_by_allowance = models.BooleanField(default=False)
    # snapshot of the shift used for the evaluation
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="attendance_days")
    shift_name = models.CharField(max_length=100, blank=True)
    expected_start = models.DateTimeField(null=True, blank=True)
    expected_end = models.DateTimeField(null=True, blank=True)
    grace_minutes = models.PositiveIntegerField(default=0)
    is_working_day = models.BooleanField(default=True)
    evaluated_at = models.DateTimeField()
    # approved request (leave or excuse) that affected this day
    request = models.ForeignKey("attendance.Request", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="attendance_days")
    excused_late_minutes = models.PositiveIntegerField(default=0)
    excused_early_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="attendanceday_unique_user_date"),
        ]


class WebPunchPolicy(BaseModel):
    department = models.OneToOneField(Department, on_delete=models.CASCADE,
                                      related_name="web_punch_policy")
    require_trusted_device = models.BooleanField(default=False)
    require_office_ip = models.BooleanField(default=False)
    allowed_ips = models.JSONField(default=list, blank=True)


class LeaveType(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    pay_percent = models.PositiveSmallIntegerField(
        default=100, validators=[MinValueValidator(0), MaxValueValidator(100)])
    uses_balance = models.BooleanField(default=False)
    yearly_allowance = models.DecimalField(
        max_digits=5, decimal_places=1, default=0, validators=[MinValueValidator(0)])
    requires_attachment = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class LeaveAllowance(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="leave_allowances")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name="allowances")
    year = models.PositiveSmallIntegerField()
    days = models.DecimalField(max_digits=5, decimal_places=1, validators=[MinValueValidator(0)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "leave_type", "year"],
                                    name="leaveallowance_unique_user_type_year"),
        ]


class Request(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendance_requests")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="requests_created")
    kind = models.CharField(max_length=20, choices=RequestKind.choices)
    status = models.CharField(max_length=20, choices=RequestStatus.choices,
                              default=RequestStatus.PENDING)
    start_date = models.DateField()
    end_date = models.DateField()
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="requests")
    minutes = models.PositiveIntegerField(null=True, blank=True)
    punch_time = models.DateTimeField(null=True, blank=True)
    cancels = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True,
                                related_name="cancellations")
    details = models.TextField(max_length=500, blank=True)
    attachment = models.FileField(upload_to="attendance-requests/", null=True, blank=True)
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="requests_decided")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(max_length=500, blank=True)
    over_balance = models.BooleanField(default=False)
    leave_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    punch = models.OneToOneField(Punch, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="request")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "start_date"], name="request_user_start_idx"),
            models.Index(fields=["status"], name="request_status_idx"),
        ]

    def __str__(self):
        return f"{self.user} {self.kind} {self.start_date}"


class PeriodClose(models.Model):
    """A closed payroll period; its attendance data is frozen. Reopening deletes the row."""
    period = models.CharField(max_length=7, unique=True)  # "YYYY-MM"
    start = models.DateField()
    end = models.DateField()
    closed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="periods_closed")
    closed_at = models.DateTimeField()


class PeriodCloseLog(BaseModel):
    ACTIONS = [("close", "Close"), ("reopen", "Reopen")]
    period = models.CharField(max_length=7)
    action = models.CharField(max_length=6, choices=ACTIONS)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="period_close_logs")
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
