from api_views.models import APIViewSet
from apps.users.models import Project
from apps.users.serializers import ProjectSerializer
from .pagination import DefaultPagination
from permissions.users import IsSuperUser, IsOwner

class ProjectViewSet(APIViewSet):
    """
    API ViewSet for Project CRUD operations.
    Inherits from project's custom APIViewSet to maintain consistency in
    filtering, pagination, and permissions.
    """
    # permission_classes = [IsAuthenticated]
    pagination_class = DefaultPagination
    model = Project
    model_serializer = ProjectSerializer
    order_by = ('name',)
    search_filters = ["uuid", 'name']
    creating_filters = ["name", "logo"]
    requiered_fields = ['name']
    updating_filters = ["name", "logo"]
    unique_field: str = 'uuid'
    
    # Custom permissions for Project operations
    permissions_config = {
        "POST": [IsSuperUser | IsOwner],
        "PUT": [IsSuperUser | IsOwner],
        "DELETE": [IsSuperUser | IsOwner],
    }
