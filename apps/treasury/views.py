from rest_framework.decorators import api_view , permission_classes
from rest_framework.request import Request
from rest_framework.response import Response
# from permissions.models import CustomBasePermission
from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from utils.parsers import parse_date
from permissions.users import IsOwner, IsSuperUser , IsManager , IsHR
from apps.users.views import DefaultPagination
from .serializer import (
    AdvanceSerializer , 
    Advance , 
    TreasuryOutcome , 
    TreasuryIncome , 
    TreasuryOutcomeSerializer ,
    TreasuryIncomeSerializer , 
    Notification ,
    NotificationSerializer,
    )
from api_views.models import APIViewSet
from django.utils.timezone import now
# Create your views here.



class AdvancesAPIView(APIViewSet):
    permission_classes = [IsAuthenticated]
    allowed_methods = ["GET","POST","PUT","DELETE"]
    pagination_class = DefaultPagination
    model = Advance
    model_serializer= AdvanceSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid",'user','status',"creator","amount","created_at"]
    creating_filters = ["user","status","creator","amount"]
    requiered_fields = ["user","status","creator","amount"]
    unique_field:str = 'uuid'
    permissions_config = {
        "PUT": [IsSuperUser | IsOwner],
        "DELETE": [IsSuperUser | IsOwner],
    }


class OutcomeAPIView(APIViewSet):
    permission_classes = [IsSuperUser | IsOwner]
    allowed_methods = ["GET","POST","DELETE"]
    pagination_class = DefaultPagination
    model = TreasuryOutcome
    model_serializer= TreasuryOutcomeSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid",'details',"creator","amount","created_at"]
    creating_filters = ["details","creator","amount"]
    requiered_fields = ["details","creator","amount"]
    unique_field:str = 'uuid'



class IncomeAPIView(APIViewSet):
    permission_classes = [IsSuperUser | IsOwner]
    allowed_methods = ["GET","POST","DELETE"]
    pagination_class = DefaultPagination
    model = TreasuryIncome
    model_serializer= TreasuryIncomeSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid",'details',"creator","amount","created_at"]
    creating_filters = ["details","creator","amount"]
    requiered_fields = ["details","creator","amount"]
    unique_field:str = 'uuid'


class NotificationAPIView(APIViewSet):
    permission_classes = [IsAuthenticated]
    allowed_methods = ["GET","POST","DELETE"]
    pagination_class = DefaultPagination
    model = Notification
    model_serializer= NotificationSerializer
    order_by = ('-created_at',)
    search_filters = ["uuid",'creator',"message"]
    creating_filters = ["creator","message","for_users","deadline"]
    requiered_fields = ["creator","message","for_users","deadline"]
    unique_field:str = 'uuid'
    permissions_config = {
        "POST": [IsSuperUser | IsOwner | IsManager | IsHR],
        "PUT": [IsSuperUser | IsOwner | IsManager | IsHR],
        "DELETE": [IsSuperUser | IsOwner | IsManager | IsHR],
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated , IsSuperUser | IsOwner])
def total_treasury(request:Request):
    date = request.query_params.get("date",None)
    date_parsed = parse_date(date,[
                "%Y-%m", 
                "%m-%Y",
                "%m/%Y", 
                "%Y/%m", 
                ]) if date else None
    
    income = TreasuryIncome.objects.aggregate(total_sum=Sum('amount'))['total_sum']
    outcome = TreasuryOutcome.objects.aggregate(total_sum=Sum('amount'))['total_sum']
    if date_parsed :
        income = TreasuryIncome.objects.filter(created_at__month=date_parsed.month , created_at__year=date_parsed.year).aggregate(total_sum=Sum('amount'))['total_sum']
        outcome = TreasuryOutcome.objects.filter(created_at__month=date_parsed.month , created_at__year=date_parsed.year).aggregate(total_sum=Sum('amount'))['total_sum']
    
    return Response({
        "income":income if income else 0,
        "outcome":outcome if outcome else 0,
        "total":(income if income is not None else 0) - (outcome if outcome is not None else 0) ,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_notification(request:Request):
    nots = Notification.objects.filter(for_users=request.user,deadline__gte = now()).order_by("-created_at")  #.exclude(seen_by_users=user)
    return Response(NotificationSerializer(nots,many=True).data) 



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def seen_notification(request:Request):
    notification_uuid = request.query_params.get("uuid","")
    if not notification_uuid:
        return Response({"details":"You must provide a notification uuid"})
    noti = Notification.objects.get(uuid=notification_uuid)
    noti.seen_by_users.add(request.user)
    return Response(NotificationSerializer(noti).data) 

