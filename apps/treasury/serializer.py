# from rest_framework.serializers import ModelSerializer
from api_views.serializers import ModelSerializer , ForeignField , ManyToManyField
from .models import TreasuryIncome , TreasuryOutcome ,Advance
from apps.users.serializers import UserSerializer , User 

class TreasuryIncomeSerializer(ModelSerializer):
    creator = UserSerializer(read_only=True)

    class Meta:
        model = TreasuryIncome
        fields = [
            "uuid",
            "creator",
            "amount",
            "details",
            "created_at",
            "updated_at",
        ]
        foreign_models = {
            "creator" : ForeignField("creator",User,"uuid")
        }



class TreasuryOutcomeSerializer(ModelSerializer):
    creator = UserSerializer(read_only=True)
    class Meta:
        model = TreasuryOutcome
        fields = [
            "uuid",
            "creator",
            "amount",
            "details",
            "from_advance",
            "created_at",
            "updated_at",
        ]
        foreign_models = {
            "creator" : ForeignField("creator",User,"uuid")
        }




class AdvanceSerializer(ModelSerializer):
    creator = UserSerializer(read_only=True)
    user = UserSerializer(read_only=True)
    class Meta:
        model = Advance
        fields = [
            "uuid",
            "creator",
            "amount",
            "user",
            "status",
            "created_at",
            "updated_at",
        ]

        foreign_models = {
            "creator" : ForeignField("creator",User,"uuid") ,
            "user" : ForeignField("user",User,"uuid"),
        }

