# from rest_framework.serializers import  ModelSerializer
from api_views.models import ForeignField , ManyToManyField 
from api_views.serializers import ModelSerializer 
from rest_framework.serializers import Serializer
from apps.users.models import User
from apps.commission.models import (
    CoinChanger,
    DeductionRules,
    TargetSlice,
    Team,
    UserCommissionDetails,
    BasicRecord ,
    Commission ,
    Subscription ,
    Additional
)
from apps.users.serializers import UserSerializer , DepartmentSerializer


class CoinChangerSerializer(ModelSerializer):
    class Meta:
        model = CoinChanger
        fields = [
            "uuid",
            "egp_to_sar",
            "date",
            "created_at",
        ]



class DeductionRulesSerializer(ModelSerializer):
    department = DepartmentSerializer()
    class Meta:
        model = DeductionRules
        fields = [
            "uuid",
            "late_time",
            "deduction_days",
            "is_global",
            "department",
        ]

class TargetSliceSerializer(ModelSerializer):
    department = DepartmentSerializer()
    class Meta:
        model = TargetSlice
        fields = [
            "uuid",
            "name",
            "min_value",
            "max_value",
            "money",
            "is_global",
            "is_money_percentage",
            "department",
        ]


class TeamSerializer(ModelSerializer):
    commission_rules = TargetSliceSerializer(many=True , read_only=True)
    leader = UserSerializer(read_only=True)
    agents = UserSerializer(many=True , read_only=True)
    class Meta:
        model = Team
        fields = [
            "uuid",
            "name",
            "leader",
            "agents",
            "commission_rules",
        ]
        many_to_many_models = {
            "commission_rules": ManyToManyField("commission_rules",TargetSlice,'uuid') ,
            "agents": ManyToManyField("agents",User,'uuid') ,
        }
        foreign_models = {
            "leader": ForeignField("leader",User,'uuid') ,
        }


class UserCommissionDetailsSerializer(ModelSerializer):
    deduction_rules = DeductionRulesSerializer(many=True, read_only=True)
    commission_rules = TargetSliceSerializer(many=True , read_only=True)
    user = UserSerializer(read_only=True)
    class Meta :
        model = UserCommissionDetails
        fields = [
            "uuid",
            "user",
            "basic",
            "set_deduction_rules",
            "deduction_rules",
            "set_global_commission_rules",
            "commission_rules",
            "will_arrive_at",
            "will_leave_at",
        ]
        many_to_many_models = {
            "deduction_rules": ManyToManyField("deduction_rules",DeductionRules,'uuid') ,
            "commission_rules": ManyToManyField("commission_rules",TargetSlice,'uuid') ,
        }
        


class BasicRecordSerializer(ModelSerializer):
    user = UserSerializer(read_only=True)
    class Meta :
        model = BasicRecord
        fields = [
            "uuid",
            "user",
            "deduction_days",
            "deduction_money",
            "kpi",
            "gift",
            "date",
            "take_annual",
            "basic",
        ]
        foreign_models = {
            "user": ForeignField("user",User,'uuid') ,
        }




class CommissionSerializer(ModelSerializer):
    basic = BasicRecordSerializer(read_only=True)
    user = UserSerializer(read_only=True)
    class Meta :
        model = Commission
        fields = [
            "uuid",
            "user",
            "basic",
            "target",
            "target_Team" ,
            "plus" ,
            "american" ,
            "american_count" ,
            "subscriptions" ,
            "subscriptions_count",
            "deduction" ,
            "gift" ,
            "salary" ,
            "date" ,
        ]
        foreign_models = {
            "user": ForeignField("user",User,'uuid') ,
            "basic": ForeignField("basic",BasicRecord,'uuid') ,
        }
        
        
        
class SubscriptionSerializer(ModelSerializer):
    class Meta :
        model = Subscription
        fields = [
            "uuid",
            "count",
            "value",
        ]
        
        
class AdditionalSerializer(ModelSerializer):
    class Meta :
        model = Additional
        fields = [
            "uuid",
            "plus",
            "american_leads",
        ]
