from .pagination import DefaultPagination, CustomPagination, Pagination1K
from api_views.models import APIViewSet 
from apps.users.models import (
    User , 
    Project , 
    Department , 
    Lead,
    )
from apps.users.serializers import (
    ProjectSerializer , 
    DepartmentSerializer , 
    UserSerializer , 
    LeadSerializer ,
    )
from .project_department_views import ProjectViewSet, DepartmentViewSet

from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import FormParser , MultiPartParser 
from permissions.users import IsAgent , IsManager , IsHR , IsOwner , IsSuperUser




class LeadAPI(APIViewSet):
    # permission_classes = [IsAuthenticated]
    pagination_class = DefaultPagination
    model = Lead
    model_serializer= LeadSerializer
    order_by = ('date',)
    search_filters = ["uuid","user","phone","name","date","project"]
    creating_filters = ["phone","name","user","date","project"]
    requiered_fields = ["user","phone","date","project"]
    unique_field:str = 'uuid'
