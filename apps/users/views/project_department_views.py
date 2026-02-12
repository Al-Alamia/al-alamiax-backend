from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated
from apps.users.models import Project, Department
from apps.users.serializers import ProjectSerializer, DepartmentSerializer
from .pagination import DefaultPagination
from permissions.users import IsSuperUser, IsOwner

class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all().order_by('name')
    serializer_class = ProjectSerializer
    pagination_class = DefaultPagination
    lookup_field = 'uuid'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['uuid', 'name']
    ordering_fields = ['name']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            self.permission_classes = [IsSuperUser | IsOwner]
        else:
            self.permission_classes = [IsAuthenticated]
        return super().get_permissions()

class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all().order_by('name')
    serializer_class = DepartmentSerializer
    pagination_class = DefaultPagination
    lookup_field = 'uuid'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['uuid', 'name']
    ordering_fields = ['name']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            self.permission_classes = [IsSuperUser | IsOwner]
        else:
            self.permission_classes = [IsAuthenticated]
        return super().get_permissions()
