from api_views.models import APIViewSet
from permissions.users import IsSuperUser ,IsOwner
from apps.users.views import DefaultPagination , IsAuthenticated , Pagination1K
from apps.commission.models import (
    Commission ,
    )
from apps.commission.serializers import (
    CommissionSerializer ,
    )


class CommissionAPI(APIViewSet):
    permission_classes = [IsSuperUser , IsOwner]
    allowed_methods = ["GET","PUT","POST","DELETE"]
    pagination_class = DefaultPagination
    model = Commission
    model_serializer= CommissionSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid","date", "user" ]
    creating_filters = [
                "user" ,
                "target" ,
                "target_Team" ,
                "plus"  ,
                "american"  ,
                "american_count"  ,
                "subscriptions"  ,
                "subscriptions_count"  ,
                "deduction" ,
                "gift"  ,
                "salary" ,
                "date"   ,
                
        ]
    requiered_fields = [
                "user" ,
                "target" ,
                "target_Team" ,
                "plus"  ,
                "american"  ,
                "american_count"  ,
                "subscriptions"  ,
                "subscriptions_count"  ,
                "deduction" ,
                "gift"  ,
                "salary" ,
                "date"   ,
        ]
    updating_filters = [
                "target" ,
                "target_Team" ,
                "plus"  ,
                "american"  ,
                "american_count"  ,
                "subscriptions"  ,
                "subscriptions_count"  ,
                "deduction" ,
                "gift"  ,
                "salary" ,
        ]
    unique_field:str = 'uuid'
