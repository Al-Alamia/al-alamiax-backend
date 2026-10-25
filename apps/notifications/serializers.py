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
