from apps.users.serializers import User , UserSerializer 
from django.db.models import Case, When, IntegerField , F , Q , Value  , Exists , CharField , OuterRef 
from rest_framework.decorators import api_view , permission_classes
from apps.users.views import IsOwner , IsSuperUser , IsManager , IsHR
from apps.commission.serializers import UserCommissionDetails , UserCommissionDetailsSerializer , BasicRecord , Commission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
import datetime


@api_view(["GET"])
@permission_classes([IsOwner | IsSuperUser | IsManager | IsHR])
def get_users_with_has_basic(request:Request):
    date = request.query_params.get("date",None)
    if date :
        first = datetime.datetime.strptime(date, "%Y-%m")
        first = datetime.datetime(first.year , first.month , 1)        
        users_with_basic_annotation = User.objects\
            .filter(is_superuser=False)\
            .exclude(role="OWNER")\
            .annotate(
                has_basic=Case(
                    When(
                        basicrecord__date__year = first.year ,
                        basicrecord__date__month = first.month , 
                        then=F("basicrecord__basic"),
                     ),
                    When(
                        Exists(
                            BasicRecord.objects.filter(user=OuterRef("uuid"), date__year = first.year , date__month = first.month  )
                        ),
                        then= Value(-1) ,
                     ),
                    default=None,
                    output_field=IntegerField(),
                ),
            ).filter(Q(has_basic__gte = 0)|Q(has_basic__isnull=True)).order_by("department","project","role").distinct() # Q(has_basic__gte=0)| Q(has_basic__isnull=True)

        return Response({
            "results":UserSerializer(users_with_basic_annotation,many=True).data
        }) 
    else :
        return Response({},HTTP_400_BAD_REQUEST)




@api_view(["GET"])
@permission_classes([IsOwner | IsSuperUser | IsManager])
def get_users_with_basic_commission(request:Request):
    date = request.query_params.get("date",None)
    department = request.query_params.get("department","")
    
    if date :
        first = datetime.datetime.strptime(date, "%Y-%m")
        first = datetime.datetime(first.year , first.month , 1)       
        
        f = {"is_superuser":False } 
        if department :
            f.update({"department__name":department})
        users_with_basic_annotation = User.objects\
            .filter(**f)\
            .exclude(role="OWNER")\
            .annotate(
                has_basic=Case(
                    When(
                        basicrecord__date__year = first.year ,
                        basicrecord__date__month = first.month , 
                        then=F("basicrecord__basic"),
                     ),
                    When(
                        Exists(
                            BasicRecord.objects.filter(user=OuterRef("uuid"), date__year = first.year , date__month = first.month  )
                        ),
                        then= Value(-1) ,
                     ),
                    default=None,
                    output_field=IntegerField(),
                ),
                has_commission= Case(
                    When(
                        commission__date__year = first.year ,
                        commission__date__month = first.month , 
                        then=F("commission__salary"),
                     ),
                    When(
                        Exists(
                            Commission.objects.filter(user=OuterRef("uuid"), date__year = first.year , date__month = first.month  )
                        ),
                        then= Value(-1) ,
                     ),
                    default=None,
                    output_field=IntegerField(),
                ),
            )\
            .filter(Q(has_basic__gte = 0)|Q(has_basic__isnull=True))\
                .filter(Q(has_commission__gte = 0)|Q(has_commission__isnull=True))\
                    .order_by("department","project","role")\
                    .distinct()
            

        return Response({
            "results":UserSerializer(users_with_basic_annotation,many=True).data
        }) 
    else :
        return Response({},HTTP_400_BAD_REQUEST)









