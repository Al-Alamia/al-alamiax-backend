from apps.users.serializers import User  
# from django.db.models import Case, When, IntegerField , F , Q , Value  , Exists , CharField , OuterRef 
from rest_framework.decorators import api_view , permission_classes
from apps.users.views import IsOwner , IsSuperUser , IsManager
from apps.commission.serializers import UserCommissionDetails  , TargetSliceSerializer , TargetSlice , Team , TeamSerializer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST , HTTP_200_OK


@api_view(["GET","POST"])
@permission_classes([IsOwner | IsSuperUser | IsManager])
def get_target_slices(request:Request):
    user_uuid = request.query_params.get("user_uuid",request.data.get("user_uuid",None))
    table_type = request.query_params.get("table_type",request.data.get("table_type",None))
    if user_uuid :
        if table_type == "team" :
            user = User.objects.get(uuid=user_uuid)
            team = Team.objects.filter(leader=user).first()
            if all([user,team]):
                result_queryset = team.commission_rules.all()
                return Response({"count":team.name,"results":TargetSliceSerializer(result_queryset.order_by("min_value").distinct(),many=True).data},HTTP_200_OK)
            return Response({"count":"NoTeam","results":[]},HTTP_200_OK)
        else :
            details = UserCommissionDetails.objects.get( user__uuid = user_uuid )
            result_queryset = details.commission_rules.all()
            if details.set_global_commission_rules :
                result_queryset = TargetSlice.objects.filter(is_global=True,department=details.user.department) | details.commission_rules.all()
            return Response({"count":"Personal","results":TargetSliceSerializer(result_queryset.order_by("min_value").distinct(),many=True).data},HTTP_200_OK)
    return Response({},HTTP_400_BAD_REQUEST)








