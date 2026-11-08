# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Al-AlamiaX backend — Django 3.2 + Django REST Framework API for an internal CRM/HR/payroll system (users, attendance via ZKTeco fingerprint devices, leads, commissions/salaries, treasury). The Next.js frontend lives in the sibling repo `../al-alamiax-frontend` (its code and its own CLAUDE.md are on the `dev` branch; `main` there is nearly empty).

## Commands

```bash
pip install -r requirements.txt   # pins are old (numpy 1.21 / pandas 1.3.5) — use Python ≤ 3.10
python manage.py migrate
python manage.py runserver
python manage.py makemigrations <app>   # apps: users, commission, treasury, purposes

python manage.py test                                          # all tests
python manage.py test apps.users.tests.test_leads              # one module
python manage.py test apps.users.tests.test_leads.LeadTests.test_create_lead   # one test
```

Database is SQLite (`db.sqlite3`, gitignored); a Postgres config is left commented out in `project/settings.py`. `TIME_ZONE = 'Africa/Cairo'` with `USE_TZ = False` (naive datetimes everywhere). Custom management commands in `apps/users/management/commands/` (`sync_fp`, `export_fp`, `temp`) still import from the pre-refactor path `users.models` and will fail until changed to `apps.users.models`.

## Architecture

### Layout
- `project/` — settings and root URLs. Routes: `api/users/`, `api/commission/`, `api/treasury/`, `api/hr-management/` (the `purposes` app), plus `admin/`.
- `apps/<app>/` — domain apps. `users` and `commission` split code into `api/urls.py`, `views/`, `serializers/` packages; `treasury` and `purposes` use flat `urls.py`/`views.py`/`serializers.py`.
- Top-level shared packages (not Django apps): `core/` (`BaseModel`, attendance `Calculator`), `api_views/` (generic CRUD view base), `permissions/` (role permissions), `auth/` (login/JWT mixins), `utils/` (validators, upload paths, Telegram notifier, error decorator).

### Models
All domain models inherit `core.models.BaseModel`: **UUID primary key named `uuid`**, plus `created_at`/`updated_at`. `AUTH_USER_MODEL = 'users.User'`; JWT `USER_ID_FIELD` is `uuid`. User roles are `apps/users/types.py:UserTypes` (AGENT, MANAGER, OWNER, HR) on `User.role`, separate from `is_superuser`.

Signals (wired at the bottom of `apps/users/models.py` and `apps/treasury/models.py`) matter when changing models:
- `create_update_history` (pre_save) snapshots the old row as JSON into `UpdateHistory`; the acting user is read from a `__by` attribute that `APIViewMixins._put` sets on the instance.
- Creating/deleting a `User` (`fp_signal` / `fp_delete`) connects to the ZKTeco device from the default `ZKConfig` (fallback `192.168.11.157:4370`) to register/remove the fingerprint user.
- `post_save` on `Advance` creates a treasury record; `post_save` on `User` creates its `Profile`.

### Generic CRUD views (`api_views/`)
Most endpoints are subclasses of `api_views.models.APIViewSet`, a single `APIView` that handles GET/POST/PUT/DELETE on one URL, configured by class attributes:
- `model`, `model_serializer`, `order_by`, `pagination_class` (from `apps/users/views/pagination.py`).
- `search_filters` — whitelist of query params that `RequestParser` turns into `Model.objects.filter(**params)` for GET.
- `unique_field` (usually `'uuid'`) — PUT and DELETE take the target id as a **query param** (`?uuid=...`), not a path segment.
- `allowed_methods` — restrict verbs (others return 405).
- `permissions_config = {"GET": [...], "POST": [...], ...}` — per-method permission classes. `get_permissions()` reads **only** this dict and overwrites `permission_classes`, so a view that only sets `permission_classes` (several in `apps/commission/views/__init__.py` do) effectively has no permission checks.

Errors raised as `api_views.exceptions` types are converted to 400 responses by `APIViewSet.wrapper`. Some newer endpoints (projects/departments, `purposes`) use standard DRF `ModelViewSet`s with `<uuid:uuid>` path params instead, and many one-off endpoints are function views with `@api_view`.

### Permissions (`permissions/`)
`CustomBasePermission` extends DRF permissions with `filter_objects_by()` / `exclude_objects_by()`, returning `{ModelName: {filter kwargs}}`. `APIViewMixins.filter_queryset_with_permissions` applies these to every queryset — e.g. non-superuser roles never see superusers or OWNER users, and only see non-global `TargetSlice`s. Role classes (`IsAgent`, `IsManager`, `IsHR`, `IsOwner`, `IsSuperUser`, `AllowAnyAuthenticated`) live in `permissions/users.py` and are combined with `|`.

### Authentication
JWT via simplejwt, but the token is accepted from the `Authorization` **cookie, header, or JSON body** (`apps/users/AuthenticationClasses.py`); the raw token is used without a `Bearer` prefix check in the custom classes. Login (`apps/users/views/authenticate.py`) returns serialized user + token + expiry and sets the cookie. Non-superusers must also present a registered device id (`unique_id`, matched against `FingerPrintID`) or login fails.

### Attendance & payroll logic
`core/calculator.py:Calculator` computes duration, lateness and early departure from `ArrivingLeaving` against each user's `UserCommissionDetails.will_arrive_at`/`will_leave_at`, and maps lateness to deduction days via `DeductionRules` (global rules or per-user rules, highest `late_time` threshold first). Arrive/leave endpoints are in `apps/users/views/arrive_leave.py`; salary/commission models are in `apps/commission/models.py`.

### Tests
Tests exist only in `apps/users/tests/`. They extend `BaseUserTestCase` (`base.py`), which creates a project, department, superuser, agent and a `FingerPrintID`, and authenticates with `self.authenticate_as(user)` (`force_authenticate`). Tests hit URLs by literal path (e.g. `/api/users/lead`). Since creating a `User` triggers the ZK fingerprint signal, tests attempt a device connection.
