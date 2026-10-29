# from rest_framework.serializers import  ModelSerializer
from api_views.models import ForeignField , ManyToManyField 
from api_views.serializers import ModelSerializer 
from rest_framework.serializers import Serializer
from apps.users.models import User
from apps.commission.models import (
    BasicRecord ,
    Commission ,
)
from apps.users.serializers import UserSerializer , DepartmentSerializer


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
