import uuid as uuid_lib

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.commission.models import UserCommissionDetails
from apps.users.admin_permissions import assignable_roles, can_manage_user
from apps.attendance.permissions import is_hr_plus
from apps.users.models import Department, Project, User
from apps.users.types import UserTypes
from apps.users.views.passwords import _invalid_new_password

MAX_BASIC_SALARY = 2_000_000_000
_TEXT_LIMITS = {"first_name": 150, "last_name": 150, "username": 150, "title": 100,
                "crm_username": 200, "fp_id": 200}


class UserAdminError(Exception):
    def __init__(self, type, message, status=400):
        super().__init__(message)
        self.type = type
        self.message = message
        self.status = status


def _text(data, name, required=False):
    value = data.get(name)
    if value is None:
        if required:
            raise UserAdminError("invalid", f"'{name}' is required.")
        return ""
    if not isinstance(value, str):
        raise UserAdminError("invalid", f"'{name}' must be a string.")
    value = value.strip()
    if required and not value:
        raise UserAdminError("invalid", f"'{name}' is required.")
    if len(value) > _TEXT_LIMITS[name]:
        raise UserAdminError("invalid", f"'{name}' is too long (max {_TEXT_LIMITS[name]}).")
    return value


def _fk(model, raw, label):
    if raw in (None, ""):
        return None
    try:
        uid = uuid_lib.UUID(str(raw))
    except ValueError:
        uid = None
    obj = model.objects.filter(uuid=uid).first() if uid else None
    if obj is None:
        raise UserAdminError("invalid", f"Invalid {label}.")
    return obj


def _check_role(actor, role, current=None):
    if role not in UserTypes.values:
        raise UserAdminError("invalid", "Invalid role.")
    if role != current and role not in assignable_roles(actor):
        raise UserAdminError("role_not_allowed", "You are not allowed to assign this role.", 403)


def _check_unique(username, fp_id, exclude=None):
    users = User.objects.all()
    if exclude is not None:
        users = users.exclude(pk=exclude.pk)
    if users.filter(username__iexact=username).exists():
        raise UserAdminError("duplicate_username", "This username is already taken.")
    if fp_id and users.filter(fp_id=fp_id).exists():
        raise UserAdminError("duplicate_fp_id", "This fingerprint ID is already used.")


def _basic_salary(raw):
    if raw in (None, ""):
        return 0
    if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not (str(raw).strip().isascii() and str(raw).strip().isdecimal()):
        raise UserAdminError("invalid", "'basic_salary' must be a non-negative integer.")
    value = int(raw)
    if value > MAX_BASIC_SALARY:
        raise UserAdminError("invalid", "'basic_salary' is too large.")
    return value


def _check_password(password, user):
    message = _invalid_new_password(password)
    if message is None:
        try:
            validate_password(password, user)
        except ValidationError as exc:
            message = " ".join(exc.messages)
    if message:
        raise UserAdminError("invalid", message)


def create_user(actor, data) -> User:
    if not is_hr_plus(actor):
        raise UserAdminError("forbidden", "You are not allowed to create users.", 403)
    username = _text(data, "username", required=True)
    first_name, last_name = _text(data, "first_name"), _text(data, "last_name")
    title, crm_username, fp_id = _text(data, "title"), _text(data, "crm_username"), _text(data, "fp_id")
    role = data.get("role") or UserTypes.AGENT
    _check_role(actor, role)
    department = _fk(Department, data.get("department"), "department")
    project = _fk(Project, data.get("project"), "project")
    basic = _basic_salary(data.get("basic_salary"))
    extra = {"title": title} if title else {}
    try:
        with transaction.atomic():
            _check_unique(username, fp_id)
            user = User(username=username, first_name=first_name, last_name=last_name, role=role,
                        crm_username=crm_username, fp_id=fp_id, department=department, project=project,
                        **extra)
            _check_password(data.get("password"), user)
            user.set_password(data["password"])
            setattr(user, "__by", actor)
            user.save()
            UserCommissionDetails.objects.update_or_create(user=user, defaults={"basic": basic})
    except IntegrityError:
        raise UserAdminError("duplicate_username", "This username or fingerprint ID is already used.")
    return user


def update_user(actor, user, data) -> User:
    if not can_manage_user(actor, user):
        raise UserAdminError("forbidden", "You are not allowed to edit this user.", 403)
    values = {}
    for name in ("first_name", "last_name", "username", "title", "crm_username", "fp_id"):
        if name in data:
            values[name] = _text(data, name, required=name == "username")
    if "title" in values and not values["title"]:  # same as create: blank falls back to the model default
        values["title"] = User._meta.get_field("title").get_default()
    if "role" in data:
        role = data["role"]
        if role != user.role:
            if actor.pk == user.pk:
                raise UserAdminError("self_change", "You cannot change your own role.")
            _check_role(actor, role, current=user.role)
            values["role"] = role
    if "department" in data:
        values["department"] = _fk(Department, data["department"], "department")
    if "project" in data:
        values["project"] = _fk(Project, data["project"], "project")
    try:
        with transaction.atomic():
            if "username" in values or values.get("fp_id"):
                _check_unique(values.get("username", user.username), values.get("fp_id", ""), exclude=user)
            for name, value in values.items():
                setattr(user, name, value)
            setattr(user, "__by", actor)
            user.save()
    except IntegrityError:
        raise UserAdminError("duplicate_username", "This username or fingerprint ID is already used.")
    return user


def revoke_refresh_tokens(user) -> None:
    """Blacklist every outstanding refresh token so the user's sessions end."""
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def set_active(actor, user, active: bool) -> User:
    if not can_manage_user(actor, user):
        raise UserAdminError("forbidden", "You are not allowed to change this user.", 403)
    if actor.pk == user.pk:
        raise UserAdminError("self_change", "You cannot change your own active state.")
    with transaction.atomic():
        user.is_active = active
        setattr(user, "__by", actor)
        user.save()
        if not active:
            revoke_refresh_tokens(user)
    return user
