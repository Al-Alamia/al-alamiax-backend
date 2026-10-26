from apps.users.models import FingerPrintID, User
from apps.users.types import UserTypes


def make_user(username, role=UserTypes.AGENT, department=None, **kw):
    """Create a user; extend BaseUserTestCase so the ZK fingerprint signals are disconnected."""
    kw.setdefault("password", "pass123")
    kw.setdefault("email", f"{username}@test.com")
    return User.objects.create_user(username=username, role=role, department=department, **kw)


def make_device(user, unique_id, status="approved"):
    return FingerPrintID.objects.create(user=user, unique_id=unique_id, status=status)
