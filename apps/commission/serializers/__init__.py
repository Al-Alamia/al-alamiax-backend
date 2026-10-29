# from rest_framework.serializers import  ModelSerializer
from api_views.models import ForeignField , ManyToManyField 
from api_views.serializers import ModelSerializer 
from rest_framework.serializers import Serializer
from apps.users.models import User
from apps.commission.models import (
    Commission ,
)
from apps.users.serializers import UserSerializer , DepartmentSerializer


class CommissionSerializer(ModelSerializer):
    user = UserSerializer(read_only=True)
    class Meta :
        model = Commission
        fields = [
            "uuid",
            "user",
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
        }
