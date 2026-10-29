from api_views.models import APIViewSet
from permissions.users import IsSuperUser ,IsOwner
from apps.users.views import DefaultPagination , IsAuthenticated , Pagination1K
from apps.commission.models import (
    UserCommissionDetails , 
    BasicRecord,
    Commission ,
    CoinChanger ,
    Subscription,
    )
from apps.commission.serializers import (
    UserCommissionDetailsSerializer , 
    BasicRecordSerializer ,
    CommissionSerializer ,
    CoinChangerSerializer,
    SubscriptionSerializer
    )


class UserCommissionDetailsAPI(APIViewSet):
    allowed_methods = ["GET","PUT"]
    permission_classes = [IsSuperUser ,IsOwner]
    pagination_class = DefaultPagination
    model = UserCommissionDetails
    model_serializer= UserCommissionDetailsSerializer
    order_by = ('user',)
    search_filters = ["uuid","user"]
    unique_field:str = 'uuid'
    updating_filters = ["basic"]


class CoinChangerAPI(APIViewSet):
    allowed_methods = ["GET","POST","DELETE"]
    permission_classes = [IsSuperUser|IsOwner]
    pagination_class = DefaultPagination
    model = CoinChanger
    model_serializer= CoinChangerSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid","date"]
    creating_filters = ["date","egp_to_sar"]
    requiered_fields = ["date","egp_to_sar"]
    unique_field:str = 'uuid'


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
    
    
class SubscriptionAPI(APIViewSet):
    permission_classes = [IsSuperUser , IsOwner]
    allowed_methods = ["GET"]
    pagination_class = Pagination1K
    model = Subscription
    model_serializer= SubscriptionSerializer
    search_filters = ["uuid","count","value"]
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
