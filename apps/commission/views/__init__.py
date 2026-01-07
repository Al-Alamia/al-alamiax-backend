from api_views.models import APIViewSet
from permissions.users import IsSuperUser ,IsOwner
from apps.users.views import DefaultPagination , IsAuthenticated , Pagination1K
from apps.commission.models import (
    UserCommissionDetails , 
    DeductionRules,
    TargetSlice,
    BasicRecord,
    Commission ,
    CoinChanger ,
    Team ,
    Subscription,
    )
from apps.commission.serializers import (
    UserCommissionDetailsSerializer , 
    DeductionRulesSerializer , 
    TargetSliceSerializer , 
    BasicRecordSerializer ,
    CommissionSerializer ,
    CoinChangerSerializer,
    TeamSerializer , 
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
    updating_filters = ["basic","set_deduction_rules","deduction_rules","set_global_commission_rules","commission_rules","will_arrive_at","will_leave_at"]


class DeductionRulesAPI(APIViewSet):
    permission_classes = [IsSuperUser ,IsOwner]
    pagination_class = DefaultPagination
    model = DeductionRules
    model_serializer= DeductionRulesSerializer
    order_by = ('late_time',)
    search_filters = ["uuid","is_global"]
    creating_filters = ["late_time","deduction_days","is_global","department"]
    requiered_fields = ["late_time","deduction_days"]
    updating_filters = ["late_time","deduction_days","is_global","department"]
    unique_field:str = 'uuid'

class TeamAPI(APIViewSet):
    permission_classes = [IsSuperUser ,IsOwner]
    pagination_class = DefaultPagination
    model = Team
    model_serializer= TeamSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid","leader"]
    creating_filters = ["name","leader","agents","commission_rules"]
    requiered_fields = ["name","leader","agents","commission_rules"]
    updating_filters = ["name","leader","agents","commission_rules"]
    unique_field:str = 'uuid'

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


class TargetSlicesAPI(APIViewSet):
    permission_classes = [IsSuperUser ,IsOwner]
    pagination_class = DefaultPagination
    model = TargetSlice
    model_serializer= TargetSliceSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid","is_global"]
    creating_filters = ["name","min_value","max_value","money","is_money_percentage" , "is_global" , "department"]
    requiered_fields = ["name","min_value","max_value","money","is_money_percentage" , "is_global" , "department"]
    updating_filters = ["name","min_value","max_value","money","is_money_percentage" , "is_global" , "department"]
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
