from django.db.models import Exists, OuterRef, Q
from django.http import Http404
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.lead_permissions import capabilities, row_can, scope_queryset
from apps.users.lead_roles import resolve_role
from apps.users.models import Lead, LeadAssignment, LeadScreenshot
from apps.users.serializers.lead_pipeline import (
    LeadDetailSerializer,
    LeadListSerializer,
    LeadWriteSerializer,
)
from apps.users.services.leads import LeadRuleError, log_update
from apps.users.types import AssignmentKinds, LeadStatuses, LeadUpdateTypes

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

    def _filtered_queryset(self):
        params = self.request.query_params
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
        return self._filtered_queryset().order_by("-date")

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
