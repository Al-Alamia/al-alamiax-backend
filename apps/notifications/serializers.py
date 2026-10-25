from rest_framework import serializers


def _sender(user):
    if user is None:
        return None
    name = f"{user.first_name} {user.last_name}".strip() or user.username
    return {"uuid": str(user.pk), "name": name}


class InboxItemSerializer(serializers.Serializer):
    """Serializes a NotificationRecipient row; context must carry ``now``."""

    def to_representation(self, row):
        n = row.notification
        now = self.context["now"]
        return {
            "uuid": str(n.pk),
            "kind": n.kind,
            "title": n.title,
            "message": n.message,
            "link": n.link,
            "sender": _sender(n.sender),
            "created_at": n.created_at,
            "expires_at": n.expires_at,
            "read_at": row.read_at,
            "expired": n.expires_at is not None and n.expires_at <= now,
        }


def _named(objs):
    return [{"uuid": str(o.pk), "name": o.name} for o in objs]


class SentItemSerializer(serializers.Serializer):
    """Serializes an annotated Notification (recipients_count, read_count)."""

    def to_representation(self, n):
        from apps.users.models import Department, Project, User

        a = n.audience or {}
        users = [
            {"uuid": str(u.pk), "name": _sender(u)["name"]}
            for u in User.objects.filter(pk__in=a.get("users", []))
        ]
        return {
            "uuid": str(n.pk),
            "title": n.title,
            "message": n.message,
            "link": n.link,
            "sender": _sender(n.sender),
            "audience": {
                "users": users,
                "departments": _named(Department.objects.filter(pk__in=a.get("departments", []))),
                "projects": _named(Project.objects.filter(pk__in=a.get("projects", []))),
                "roles": a.get("roles", []),
                "everyone": bool(a.get("everyone", False)),
            },
            "expires_at": n.expires_at,
            "retracted_at": n.retracted_at,
            "created_at": n.created_at,
            "recipients_count": n.recipients_count,
            "read_count": n.read_count,
        }
