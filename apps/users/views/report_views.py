from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST
from rest_framework.request import Request
from rest_framework.response import Response
from apps.users.models import User 
from apps.users.serializers import  ReportRecord ,ReportRecordSerializer
from apps.users.views import IsAuthenticated , IsOwner , IsSuperUser
from django.utils import timezone
import json


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_report(request: Request):
    data = request.data.copy()
    obj = ReportRecord(user=request.user,date = timezone.now().date() , json_data=json.dumps(data))
    obj.save()
    return Response(ReportRecordSerializer(obj).data)
    
    
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def check_report(request: Request):
    obj = ReportRecord.objects.filter(user=request.user,date = timezone.now().date() )
    return Response({"canReport":  False if obj else True})



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_reports(request: Request):
    proj_filterd = request.query_params.get("project",None)
    date_filterd = request.query_params.get("date",None)
    if date_filterd :
        date_filterd = datetime.strptime(date_filterd , '%Y-%m-%d')
    objs = ReportRecord.objects.filter(user__project__uuid= proj_filterd, date = date_filterd.date())
    # print(objs.first().date ,date_filterd.date() ) # 
    return Response({
        "results" : ReportRecordSerializer(objs,many=True).data
    })



