from collections.abc import Mapping
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import Http404
from django.utils.dateparse import parse_date
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.lead_permissions import capabilities, row_can, scope_queryset
from apps.users.lead_roles import resolve_role
from apps.users.models import Lead, LeadAssignment, LeadScreenshot, User
from apps.users.serializers.lead_pipeline import (
    LeadDetailSerializer,
    LeadListSerializer,
    LeadUpdateSerializer,
    LeadWriteSerializer,
)
from apps.users.services.leads import LeadRuleError, assign_leads, log_update, return_lead
from apps.users.types import AssignmentKinds, CallStatuses, DepartmentCodes, LeadStatuses, LeadUpdateTypes

from .pagination import DefaultPagination

CAPABILITY_MESSAGE = "You do not have permission to perform this action"


def _first_message(data):
    if isinstance(data, dict):
        data = next(iter(data.values()), "")
    if isinstance(data, (list, tuple)):
        return _first_message(data[0]) if data else ""
    return str(data)


class LeadViewSet(viewsets.ModelViewSet):
    lookup_field = "uuid"
    pagination_class = DefaultPagination
    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc):
        if isinstance(exc, LeadRuleError):
            return Response({"message": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, ValidationError):
            return Response(
                {"message": _first_message(exc.detail)}, status=http_status.HTTP_400_BAD_REQUEST
            )
        if isinstance(exc, Http404):
            return Response({"message": "Not found"}, status=http_status.HTTP_404_NOT_FOUND)
        response = super().handle_exception(exc)
        if isinstance(response.data, dict) and "detail" in response.data:
            response.data = {"message": str(response.data["detail"])}
        return response

    # ---- queryset / serializers -------------------------------------------------

    def get_serializer_class(self):
        if self.action == "retrieve":
            return LeadDetailSerializer
        if self.action in ("create", "partial_update", "update"):
            return LeadWriteSerializer
        return LeadListSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not hasattr(self, "_role"):
            self._role = resolve_role(self.request.user)
        context["role"] = self._role
        return context

    def _validated_params(self):
        params = self.request.query_params
        for field in ("project", "created_by", "assigned_to"):
            if params.get(field):
                try:
                    UUID(params[field])
                except ValueError:
                    raise ValidationError(f"Invalid {field}")
        for field in ("date_from", "date_to"):
            if params.get(field):
                try:
                    valid = parse_date(params[field]) is not None
                except ValueError:
                    valid = False
                if not valid:
                    raise ValidationError(f"Invalid {field}, expected YYYY-MM-DD")
        return params

    def _filtered_queryset(self):
        params = self._validated_params()
        qs = scope_queryset(
            self.request.user,
            Lead.objects.select_related("user", "project").prefetch_related("assignments__agent"),
            hidden=params.get("hidden") == "true",
        )
        if params.get("search"):
            term = params["search"]
            qs = qs.filter(Q(name__icontains=term) | Q(phone__icontains=term))
        for field in ("status", "call_status", "stock_market"):
            if params.get(field):
                qs = qs.filter(**{field: params[field]})
        if params.get("project"):
            qs = qs.filter(project_id=params["project"])
        if params.get("created_by"):
            qs = qs.filter(user_id=params["created_by"])
        if params.get("assigned_to"):
            qs = qs.filter(
                Exists(
                    LeadAssignment.objects.filter(
                        lead=OuterRef("pk"), is_active=True, agent_id=params["assigned_to"]
                    )
                )
            )
        if params.get("unassigned") == "true":
            qs = qs.filter(
                ~Exists(
                    LeadAssignment.objects.filter(
                        lead=OuterRef("pk"), is_active=True, kind=AssignmentKinds.SALES.value
                    )
                )
            )
        if params.get("returned") == "true":
            qs = qs.filter(return_count__gt=0)
        if params.get("date_from"):
            qs = qs.filter(date__date__gte=params["date_from"])
        if params.get("date_to"):
            qs = qs.filter(date__date__lte=params["date_to"])
        return qs

    def get_queryset(self):
        return self._filtered_queryset().order_by("-date", "-created_at")

    # ---- CRUD -------------------------------------------------------------------

    def _check_unique_phone(self, user, phone, exclude=None):
        clash = Lead.objects.filter(user=user, phone=phone)
        if exclude is not None:
            clash = clash.exclude(pk=exclude.pk)
        if clash.exists():
            raise ValidationError("A lead with this phone number already exists")

    def create(self, request, *args, **kwargs):
        if not capabilities(request.user)["create"]:
            raise PermissionDenied(CAPABILITY_MESSAGE)
        serializer = LeadWriteSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        self._check_unique_phone(request.user, data["phone"])
        if data.get("project") is None:
            data["project"] = request.user.project
        with transaction.atomic():
            lead = Lead.objects.create(user=request.user, **data)
            for image in request.FILES.getlist("screenshots"):
                LeadScreenshot.objects.create(lead=lead, image=image)
            log_update(lead, request.user, LeadUpdateTypes.CREATED.value)
        return Response(
            LeadDetailSerializer(lead, context=self.get_serializer_context()).data,
            status=http_status.HTTP_201_CREATED,
        )

    def retrieve(self, request, *args, **kwargs):
        lead = self.get_object()
        return Response(LeadDetailSerializer(lead, context=self.get_serializer_context()).data)

    def partial_update(self, request, *args, **kwargs):
        lead = self.get_object()
        if not row_can(request.user, lead, role=self.get_serializer_context()["role"])["edit"]:
            raise PermissionDenied(CAPABILITY_MESSAGE)
        serializer = LeadWriteSerializer(
            data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "phone" in data:
            self._check_unique_phone(lead.user, data["phone"], exclude=lead)
        changed = [f for f, v in data.items() if getattr(lead, f) != v]
        for field in changed:
            setattr(lead, field, data[field])
        if changed:
            lead.save(update_fields=changed)
            log_update(
                lead, request.user, LeadUpdateTypes.EDITED.value, note=", ".join(changed)
            )
        lead = self.get_queryset().get(pk=lead.pk)
        return Response(LeadDetailSerializer(lead, context=self.get_serializer_context()).data)

    def destroy(self, request, *args, **kwargs):
        lead = self.get_object()
        if not row_can(request.user, lead, role=self.get_serializer_context()["role"])["delete"]:
            raise PermissionDenied(CAPABILITY_MESSAGE)
        lead.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)

    # ---- page-level endpoints ---------------------------------------------------

    @action(detail=False, methods=["get"])
    def me(self, request):
        return Response(capabilities(request.user))

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self._filtered_queryset()
        inactive = [LeadStatuses.NOT_INTERESTED.value, LeadStatuses.SUBSCRIBER.value]
        return Response(
            {
                "total": qs.count(),
                "active": qs.exclude(status__in=inactive).count(),
                "returned": qs.filter(return_count__gt=0).count(),
                "interested": qs.filter(status=LeadStatuses.INTERESTED.value).count(),
            }
        )

    def _require_assign(self):
        if not capabilities(self.request.user)["assign"]:
            raise PermissionDenied(CAPABILITY_MESSAGE)

    @action(detail=False, methods=["post"])
    def assign(self, request):
        self._require_assign()
        data = self._payload()
        lead_ids = data.get("leads")
        if not isinstance(lead_ids, list) or not lead_ids:
            raise ValidationError("leads must be a non-empty list")
        try:
            lead_ids = {UUID(str(value)) for value in lead_ids}
            agent_id = UUID(str(data.get("agent")))
        except ValueError:
            raise ValidationError("Invalid lead or agent uuid")
        kind = data.get("kind")
        if kind not in AssignmentKinds.values:
            raise ValidationError("Invalid kind")
        agent = User.objects.filter(pk=agent_id).first()
        if agent is None:
            raise ValidationError("Agent not found")
        leads = list(scope_queryset(request.user, Lead.objects.all()).filter(pk__in=lead_ids))
        if len(leads) != len(lead_ids):
            return Response({"message": "Lead not found"}, status=http_status.HTTP_404_NOT_FOUND)
        assignments = assign_leads(request.user, leads, agent, kind)
        return Response({"assigned": len(assignments)})

    @action(detail=False, methods=["get"], url_path="assignable-agents", url_name="assignable-agents")
    def assignable_agents(self, request):
        self._require_assign()
        role = resolve_role(request.user)
        agents = User.objects.filter(department__code=DepartmentCodes.SALES.value)
        if not role.is_admin:
            agents = agents.filter(Q(uuid__in=role.team_member_ids) | Q(pk=request.user.pk))
        return Response(
            [
                {"uuid": a.uuid, "username": a.username, "name": a.get_full_name() or a.username}
                for a in agents.order_by("username")
            ]
        )

    # ---- per-lead actions -------------------------------------------------------

    def _payload(self):
        if not isinstance(self.request.data, Mapping):
            raise ValidationError("Request body must be a JSON object")
        return self.request.data

    def _require(self, lead, capability):
        if not row_can(self.request.user, lead, role=self.get_serializer_context()["role"])[
            capability
        ]:
            raise PermissionDenied(CAPABILITY_MESSAGE)

    @action(detail=True, methods=["get"])
    def updates(self, request, uuid=None):
        lead = self.get_object()
        qs = lead.updates.select_related("by").order_by("-created_at")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(LeadUpdateSerializer(page, many=True).data)

    @action(detail=True, methods=["post"])
    def notes(self, request, uuid=None):
        lead = self.get_object()
        self._require(lead, "note")
        note = str(self._payload().get("note") or "").strip()
        if not note:
            raise ValidationError("Note is required")
        update = log_update(lead, request.user, LeadUpdateTypes.NOTE.value, note=note)
        return Response(LeadUpdateSerializer(update).data, status=http_status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="return", url_name="return")
    def return_lead(self, request, uuid=None):
        lead = self.get_object()
        reason = str(self._payload().get("reason") or "")
        return_lead(request.user, lead, reason)
        lead.refresh_from_db()
        serializer = LeadDetailSerializer(lead, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="status", url_name="status")
    def set_status(self, request, uuid=None):
        lead = self.get_object()
        self._require(lead, "status")
        data = self._payload()
        note = str(data.get("note") or "").strip()
        fields = (
            ("status", LeadStatuses, LeadUpdateTypes.STATUS),
            ("call_status", CallStatuses, LeadUpdateTypes.CALL_STATUS),
        )
        changes = []
        for field, choices, update_type in fields:
            value = data.get(field)
            if value in (None, ""):
                continue
            if value not in choices.values:
                raise ValidationError(f"Invalid {field}")
            old = getattr(lead, field)
            if value != old:
                changes.append((field, update_type, old, value))
        with transaction.atomic():
            for field, update_type, old, value in changes:
                setattr(lead, field, value)
                log_update(lead, request.user, update_type.value, old, value, note)
            if changes:
                lead.save(update_fields=[c[0] for c in changes])
        lead = self.get_queryset().get(pk=lead.pk)
        return Response(LeadDetailSerializer(lead, context=self.get_serializer_context()).data)
