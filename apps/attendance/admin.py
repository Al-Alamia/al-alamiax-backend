from django.contrib import admin

from .models import (
    AttendanceDay,
    AttendanceSettings,
    DeductionPolicy,
    DeductionTier,
    Holiday,
    Punch,
    Shift,
    ShiftAssignment,
    WebPunchPolicy,
)


@admin.register(AttendanceSettings)
class AttendanceSettingsAdmin(admin.ModelAdmin):
    list_display = ["period_start_day", "device_sync_minutes", "last_nightly_run"]


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ["name", "start_time", "end_time", "grace_minutes", "active"]
    list_filter = ["active"]
    search_fields = ["name"]


@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ["shift", "department", "user", "effective_from"]
    list_filter = ["shift", "department"]


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ["date", "name", "department"]
    list_filter = ["department"]


class DeductionTierInline(admin.TabularInline):
    model = DeductionTier
    extra = 0


@admin.register(DeductionPolicy)
class DeductionPolicyAdmin(admin.ModelAdmin):
    list_display = ["department", "monthly_late_allowance", "absence_days"]
    inlines = [DeductionTierInline]


@admin.register(Punch)
class PunchAdmin(admin.ModelAdmin):
    list_display = ["user", "timestamp", "source", "device", "is_demo"]
    list_filter = ["source", "is_demo"]
    search_fields = ["user__username"]


@admin.register(AttendanceDay)
class AttendanceDayAdmin(admin.ModelAdmin):
    list_display = ["user", "date", "status", "late_minutes", "early_leave_minutes", "deduction_days"]
    list_filter = ["status", "date"]
    search_fields = ["user__username"]


@admin.register(WebPunchPolicy)
class WebPunchPolicyAdmin(admin.ModelAdmin):
    list_display = ["department", "require_trusted_device", "require_office_ip"]
