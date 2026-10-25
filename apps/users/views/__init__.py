from .pagination import DefaultPagination, CustomPagination, Pagination1K
from api_views.models import APIViewSet 
from apps.users.models import (
    User , 
    Project , 
    Department , 
    Profile,
    Lead,
    FingerPrintID ,
    )
from apps.users.serializers import (
    ProjectSerializer , 
    DepartmentSerializer , 
    UserSerializer , 
    ProfileSerializer ,
    LeadSerializer ,
    FingerPrintIDSerializer ,
    )
from .project_department_views import ProjectViewSet, DepartmentViewSet

from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import FormParser , MultiPartParser 
from permissions.users import IsAgent , IsManager , IsHR , IsOwner , IsSuperUser




class UsersAPI(APIViewSet):
    pagination_class = Pagination1K
    model = User
    model_serializer= UserSerializer
    order_by = ('-is_active','role','username')
    search_filters = ["uuid",'username','project' ,"department","role","is_active","is_superuser","crm_username"]
    creating_filters = ["username","password","is_active","role","is_staff","title","project","department","crm_username"]
    requiered_fields = ['username',"password"]
    updating_filters = ["username","is_active","role","is_staff","title","project","department","crm_username"]
    unique_field:str = 'uuid'
    permissions_config = {
        "GET": [IsSuperUser | IsOwner | IsManager | IsHR],
        "POST": [IsSuperUser | IsOwner | IsManager | IsHR],
        "PUT": [IsSuperUser | IsOwner | IsManager | IsHR],
        "DELETE": [IsSuperUser | IsOwner | IsManager | IsHR],
    }




class ProfileAPI(APIViewSet):
    parser_classes=[MultiPartParser , FormParser]
    # permission_classes = [IsAuthenticated ]
    allowed_methods = ["GET","PUT"]
    pagination_class = DefaultPagination
    model = Profile
    model_serializer= ProfileSerializer
    order_by = ('user',)
    search_filters = ["uuid",'user','about']
    updating_filters = ["phone","picture","telegram_id","about"]
    unique_field:str = 'uuid'


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




class FingerPrintIDAPI(APIViewSet):
    # permission_classes = [IsAuthenticated]
    allowed_methods = ["GET","POST","DELETE"]
    pagination_class = DefaultPagination
    model = FingerPrintID
    model_serializer= FingerPrintIDSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid","user","name","unique_id"]
    creating_filters = ["user","name","unique_id"]
    requiered_fields =  ["user","name","unique_id"]
    unique_field:str = 'uuid'
    permissions_config = {
        "POST": [IsSuperUser | IsOwner | IsManager | IsHR],
        "PUT": [IsSuperUser | IsOwner | IsManager | IsHR],
        "DELETE": [IsSuperUser | IsOwner | IsManager | IsHR],
    }
