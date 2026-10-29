from api_views.models import APIViewSet
from permissions.users import IsSuperUser ,IsOwner
from apps.users.views import DefaultPagination , IsAuthenticated , Pagination1K
from apps.commission.models import (
    BasicRecord,
    Commission ,
    )
from apps.commission.serializers import (
    BasicRecordSerializer ,
    CommissionSerializer ,
    )


class  BasicRecordAPI(APIViewSet):
    permission_classes = [IsSuperUser , IsOwner]
    allowed_methods = ["GET","PUT","POST","DELETE"]
    pagination_class = DefaultPagination
    model = BasicRecord
    model_serializer= BasicRecordSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid","user","date"]
    creating_filters = ["user","deduction_days","take_annual","deduction_money","kpi" , "gift" , "basic" , "date"]
    requiered_fields = ["user","deduction_days","take_annual","deduction_money","kpi" , "gift" , "basic" , "date"]
    updating_filters = ["deduction_days","take_annual","deduction_money","kpi" , "gift" , "basic"]
    unique_field:str = 'uuid'
    
    
class CommissionAPI(APIViewSet):
    permission_classes = [IsSuperUser , IsOwner]
    allowed_methods = ["GET","PUT","POST","DELETE"]
    pagination_class = DefaultPagination
    model = Commission
    model_serializer= CommissionSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid","basic","date", "user" ]
    creating_filters = [
                "user" ,
                "basic"  ,
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
                "basic"  ,
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
