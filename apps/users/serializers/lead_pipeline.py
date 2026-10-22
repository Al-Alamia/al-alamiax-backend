from rest_framework import serializers

from apps.users.lead_permissions import active_assignment, row_can
from apps.users.models import Project
from apps.users.types import AssignmentKinds, StockMarkets
from utils.working_days import return_days_left


def _user_ref(user):
    return {"uuid": user.uuid, "username": user.username} if user else None


def _agent_ref(assignment):
    if not assignment:
        return None
    return {
        "uuid": assignment.agent.uuid,
        "username": assignment.agent.username,
        "assigned_at": assignment.created_at,
    }


class LeadListSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    date = serializers.DateTimeField(read_only=True)
    project = serializers.UUIDField(source="project_id", read_only=True)
    project_name = serializers.SerializerMethodField()
    stock_market = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    call_status = serializers.CharField(read_only=True)
    is_hidden = serializers.BooleanField(read_only=True)
    return_count = serializers.IntegerField(read_only=True)
    created_by = serializers.SerializerMethodField()
    sales_agent = serializers.SerializerMethodField()
    cs_agent = serializers.SerializerMethodField()
    return_days_left = serializers.SerializerMethodField()
    can = serializers.SerializerMethodField()

    def get_project_name(self, obj):
        return obj.project.name if obj.project else None

    def get_stock_market(self, obj):
        return obj.stock_market or None

    def get_created_by(self, obj):
        return _user_ref(obj.user)

    def get_sales_agent(self, obj):
        return _agent_ref(active_assignment(obj, AssignmentKinds.SALES.value))

    def get_cs_agent(self, obj):
        return _agent_ref(active_assignment(obj, AssignmentKinds.CS.value))

    def get_return_days_left(self, obj):
        sales = active_assignment(obj, AssignmentKinds.SALES.value)
        return return_days_left(sales.created_at) if sales else None

    def get_can(self, obj):
        request = self.context["request"]
        return row_can(request.user, obj, role=self.context.get("role"))


class LeadDetailSerializer(LeadListSerializer):
    description = serializers.CharField(read_only=True)
    screenshots = serializers.SerializerMethodField()
    assignments = serializers.SerializerMethodField()
    returns = serializers.SerializerMethodField()

    def get_screenshots(self, obj):
        request = self.context["request"]
        return [
            {"uuid": s.uuid, "url": request.build_absolute_uri(s.image.url)}
            for s in obj.screenshots.all()
        ]

    def get_assignments(self, obj):
        return [
            {
                "uuid": a.uuid,
                "kind": a.kind,
                "agent": _user_ref(a.agent),
                "assigned_by": _user_ref(a.assigned_by),
                "is_active": a.is_active,
                "created_at": a.created_at,
            }
            for a in obj.assignments.all()
        ]

    def get_returns(self, obj):
        return [
            {
                "uuid": r.uuid,
                "returned_by": _user_ref(r.returned_by),
                "reason": r.reason,
                "created_at": r.created_at,
            }
            for r in obj.returns.select_related("returned_by")
        ]


class LeadWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    stock_market = serializers.ChoiceField(
        choices=StockMarkets.choices, required=False, allow_null=True, allow_blank=True
    )
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(), required=False, allow_null=True
    )
    date = serializers.DateTimeField(required=False)

    def validate_stock_market(self, value):
        return value or ""  # R5: stored as "" when unset


class LeadUpdateSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(read_only=True)
    type = serializers.CharField(read_only=True)
    from_value = serializers.CharField(read_only=True)
    to_value = serializers.CharField(read_only=True)
    note = serializers.CharField(read_only=True)
    by = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)

    def get_by(self, obj):
        return _user_ref(obj.by)
