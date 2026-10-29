"""Plain dict builders for the admin users API."""
from datetime import date
from decimal import Decimal

from apps.payroll_config.services import basic_for
from apps.users.admin_permissions import (
    assignable_roles, can_manage_devices, can_manage_files, can_manage_user, can_view_devices,
    can_view_files, can_view_history, is_top)
from apps.users.types import UserTypes


def user_name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def brief(obj):
    return {"uuid": str(obj.uuid), "name": obj.name} if obj is not None else None


def can_reset_password(viewer, target) -> bool:
    """Mirrors views.passwords.set_password: allowed caller roles, minus superuser/OWNER targets."""
    if not (viewer.is_superuser or viewer.role in (UserTypes.OWNER, UserTypes.MANAGER, UserTypes.HR)):
        return False
    if target.is_superuser and not viewer.is_superuser:
        return False
    if target.role == UserTypes.OWNER and not is_top(viewer):
        return False
    return True


def _picture(request, user):
    profile = getattr(user, "profile", None) if hasattr(user, "profile") else None
    if profile is not None and profile.picture:
        return request.build_absolute_uri(profile.picture.url)
    return None


def list_item(request, user) -> dict:
    viewer = request.user
    manage = can_manage_user(viewer, user)
    return {
        "uuid": str(user.uuid), "username": user.username, "name": user_name(user),
        "first_name": user.first_name, "last_name": user.last_name, "role": user.role,
        "title": user.title, "is_active": user.is_active, "crm_username": user.crm_username,
        "fp_id": user.fp_id, "department": brief(user.department), "project": brief(user.project),
        "picture": _picture(request, user),
        "can": {"edit": manage, "deactivate": manage and viewer.pk != user.pk,
                "manage_devices": can_manage_devices(viewer, user)},
    }


def detail(request, user) -> dict:
    viewer = request.user
    data = list_item(request, user)
    profile = getattr(user, "profile", None) if hasattr(user, "profile") else None
    data.update({
        "phone": profile.phone if profile else None,
        "telegram_id": profile.telegram_id if profile else None,
        "about": profile.about if profile else "",
        "basic_salary": (str(basic_for(user, date.today()) or Decimal("0.00"))
                         if (viewer.pk == user.pk or can_manage_user(viewer, user)) else None),
        "date_joined": user.date_joined, "last_login": user.last_login,
        "assignable_roles": assignable_roles(viewer),
    })
    data["can"].update({
        "view_devices": can_view_devices(viewer, user), "view_files": can_view_files(viewer, user),
        "manage_files": can_manage_files(viewer, user), "view_history": can_view_history(viewer, user),
        "reset_password": can_reset_password(viewer, user),
    })
    return data


def option(user) -> dict:
    return {"uuid": str(user.uuid), "name": user_name(user), "username": user.username,
            "role": user.role, "department": brief(user.department)}
