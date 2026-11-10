from apps.attendance.types import DayStatus


def _count(days, status) -> int:
    return sum(1 for d in days if d.status == status)


def day_summary(days) -> dict:
    present, late = _count(days, DayStatus.PRESENT), _count(days, DayStatus.LATE)
    return {
        "present": present,
        "late": late,
        "absent": _count(days, DayStatus.ABSENT),
        "incomplete": _count(days, DayStatus.INCOMPLETE),
        "weekend": _count(days, DayStatus.WEEKEND),
        "holiday": _count(days, DayStatus.HOLIDAY),
        "no_shift": _count(days, DayStatus.NO_SHIFT),
        "leave": _count(days, DayStatus.LEAVE),
        "excused": _count(days, DayStatus.EXCUSED),
        "late_minutes": sum(d.late_minutes for d in days),
        "early_leave_minutes": sum(d.early_leave_minutes for d in days),
        "deduction_days": round(sum(d.deduction_days for d in days), 2),
        "on_time_percent": round(100 * present / (present + late), 1) if present + late else 0,
    }
