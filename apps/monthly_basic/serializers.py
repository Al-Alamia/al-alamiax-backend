from decimal import Decimal


def money(value):
    return f"{Decimal(value):.2f}"


def tenth(value):
    return f"{Decimal(value):.1f}"


def user_data(user):
    dept = user.department
    return {
        "uuid": str(user.uuid),
        "name": user.get_full_name() or user.username,
        "username": user.username,
        "role": user.role,
        "department": {"uuid": str(dept.uuid), "name": dept.name} if dept else None,
    }


def user_ref(user):
    return {"uuid": str(user.uuid), "name": user.get_full_name() or user.username}


def inputs_data(record):
    return {
        "kpi": money(record.kpi if record else 0), "kpi_note": record.kpi_note if record else "",
        "gift": money(record.gift if record else 0), "gift_note": record.gift_note if record else "",
        "days_adjustment": tenth(record.days_adjustment if record else 0),
        "days_adjustment_note": record.days_adjustment_note if record else "",
        "other_deduction": money(record.other_deduction if record else 0),
        "other_deduction_note": record.other_deduction_note if record else "",
    }


def breakdown_data(values):
    out = {k: money(v) for k, v in values.items()}
    out["days_adjustment"] = tenth(values["days_adjustment"])
    out["leave_days"] = tenth(values["leave_days"])
    return out
