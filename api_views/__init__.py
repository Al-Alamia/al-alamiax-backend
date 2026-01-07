# from .mixin import (
#     PageNumberPagination ,
#     AuthenticateUser , 
# )
# from .models import APIViewSet , ForeignField , ManyToManyField
# from users.models import User , Project , Department
# from users.serializers import UserSerializer
# from permissions.models import IsAuthenticated
# from permissions.users import IsAgent


# class CustomPagination(PageNumberPagination):
#     page_size = 10
#     page_size_query_param = 'page_size'
#     max_page_size = 100

# class UsersAPI(APIViewSet):
#     permission_classes = [IsAuthenticated , IsAgent]
#     pagination_class = CustomPagination
#     model = User
#     model_serializer= UserSerializer
#     order_by = ('username',)
#     search_filters = ["uuid",'username','project']
#     creating_filters = ["username","_password","is_active","role","is_staff","title","project","department"]
#     requiered_fields = ['username',"_password"]
#     updating_filters = ["username","_password","is_active","role","is_staff","title","project","department"]
#     unique_field:str = 'uuid'
#     auth_class = AuthenticateUser
#     foreign_models = {
#         "project": ForeignField("project",Project,'uuid') ,
#         "department": ForeignField("department",Department,'uuid') ,
#     }
#     many_to_many_models = {}

