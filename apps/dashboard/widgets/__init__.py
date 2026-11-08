from apps.monthly_basic.serializers import money  # noqa: F401  (re-exported)


def user_ref(user) -> dict:
    return {"uuid": str(user.uuid), "name": user.get_full_name().strip() or user.username}
