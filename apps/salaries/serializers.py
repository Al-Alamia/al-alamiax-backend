from apps.monthly_basic.serializers import money, user_data, user_ref  # noqa: F401


def history_row(salary):
    return {
        "period": salary.period,
        "basic_net": money(salary.basic_net),
        "commission": money(salary.commission),
        "total": money(salary.total),
        "given_at": salary.given_at.isoformat() if salary.given_at else None,
    }
