from rest_framework.response import Response
from rest_framework.decorators import api_view , permission_classes
from rest_framework.request import Request
from apps.users.models import ArrivingLeaving , User
from apps.users.serializers import ArrivingLeavingSerializer
from django.utils import timezone
from apps.users.views import IsAuthenticated
import pandas as pd
from rest_framework.status import HTTP_400_BAD_REQUEST
from datetime import date, timedelta, datetime
from django.db.models import Q
from django.utils.timezone import make_aware
from django.http import FileResponse


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def arreive(request: Request):
    try :
        obj = ArrivingLeaving.objects.get(user=request.user,date=timezone.now().date())
        created = False
    except ArrivingLeaving.DoesNotExist :
        obj = ArrivingLeaving(user=request.user,date=timezone.now().date())
        obj.arriving_at = timezone.now()
        created = True    
    obj.save()
    at = obj.arriving_at.strftime('%Y/%m/%d - %H:%M:%S')
    if not created:
        return Response({"details":f"Already Arrived !! {at}","arrived_at":obj.arriving_at})
    return Response({"details":f"Successfully Arrived {created} {at}","arrived_at":obj.arriving_at})



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave(request: Request):
    try :
        obj = ArrivingLeaving.objects.get(user=request.user,date=timezone.now().date())
        obj.leaving_at = timezone.now()
        at = obj.leaving_at.strftime('%Y/%m/%d - %H:%M:%S')
        obj.save()
        return Response({"details":f"Successfully Leaved {at}","leaved_at":obj.leaving_at})
    except ArrivingLeaving.DoesNotExist :
        return Response({"details":f"You are not Arrived Yet !!"},status=HTTP_400_BAD_REQUEST)




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def arrive_leave_details(request: Request): 
    try :
        obj = ArrivingLeaving.objects.get(user=request.user,date=timezone.now().date())
        return Response({"details":f"","arrived_at":obj.arriving_at , "leaved_at":obj.leaving_at})
    except ArrivingLeaving.DoesNotExist :
        return Response({"details":f"You are not Arrived Yet !!","arrived_at":None , "leaved_at":None})




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def arrive_leave_details_table(request: Request): 
    start = request.query_params.get("start",None)
    end = request.query_params.get("end",None)
    user = request.query_params.get("user",None)
    if all( start ,  end , user ):
        date_range = pd.date_range(start=start,end=end)


        user = User.objects.get(uuid=user)
        
        try :

            

            obj = ArrivingLeaving.objects.get(user=request.user,date=timezone.now().date())
            return Response({"details":f"","arrived_at":obj.arriving_at , "leaved_at":obj.leaving_at})
        except ArrivingLeaving.DoesNotExist :
            return Response({"details":f"You are not Arrived Yet !!","arrived_at":None , "leaved_at":None})

    else :
        return Response({},HTTP_400_BAD_REQUEST)




from importlib import import_module

@api_view(["GET"])
def test(request:Request):
    code = request.data.get('code', '')
    data = {
        'Column1': ['Value1', 'Value2', 'Value3'],
        'Column2': [10, 20, 30],
        'Column3': [1.5, 2.5, 3.5],
    }

    # Create a DataFrame
    df = pd.DataFrame(data)

    # Generate an Excel file
    
    # with pd.ExcelWriter("../../media", engine='openpyxl') as writer:
    df.to_excel("example.xlsx", index=False, sheet_name='Sheet1')
        
    # response = Response(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        
    # response['Content-Disposition'] = 'attachment; filename=example.xlsx'
    response = FileResponse([],filename="example.xlsx",as_attachment=True)

    return response

    # try:
    #     # Define a safe scope with only the necessary imports and variables
    #     safe_scope = {
    #         'User': getattr(import_module("users.models") , "User"),
    #         'queryset': None,  # Ensure a known variable for the queryset
    #     }
    #     print(code)
    #     # Execute the code string
    #     exec(code, {}, safe_scope)
    #     print(safe_scope)

    #     # Extract the queryset
    #     queryset = safe_scope.get('queryset')
    #     if queryset is not None:
    #         # Use the serializer to serialize the queryset
    #         s = getattr(import_module("users.serializers"),"UserSerializer")
    #         serializer = s(queryset, many=True)
    #         return Response({'result': serializer.data})
    #     else:
    #         return Response({'error': 'No queryset defined'}, status=400)
    # except Exception as e:
    #     return Response({'error': str(e)}, status=400)









#########################################################################

from rest_framework.views import APIView






def get_date_range_for_custom_month(year, month):
    if month == 1:
        start_date = date(year - 1, 12, 26)
        end_date = date(year, 1, 24)
    else:
        start_date = date(year, month - 1, 26)
        end_date = date(year, month, 25)
    return start_date, end_date

def get_all_days_in_custom_month(start_date, end_date):
    current_day = start_date
    days = []
    while current_day <= end_date:
        if current_day.weekday() not in (4, 5):  # 4 is Friday, 5 is Saturday
            days.append(current_day)
        current_day += timedelta(days=1)
    return days

def get_monthly_history(user, year, month):
    start_date, end_date = get_date_range_for_custom_month(year, month)
    all_days = get_all_days_in_custom_month(start_date, end_date)
    
    records = ArrivingLeaving.objects.filter(
        user=user,
        date__range=(start_date, end_date)
    )

    records_lookup = {record.date: record for record in records}
    
    history = []
    for day in all_days:
        if day in records_lookup:
            record = records_lookup[day]
            history.append(record)
        else:
            history.append(ArrivingLeaving(
                user=user,
                date=day,
                arriving_at= None,
                leaving_at= None,
            ))
    return history




class MonthlyHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request:Request):
        user_id = request.query_params.get("user_id")
        year = int(request.query_params.get("year"))
        month = int(request.query_params.get("month"))
        user = User.objects.get(uuid=user_id)
        history = get_monthly_history(user, year, month)
        serializer = ArrivingLeavingSerializer(history, many=True)
        return Response({"results":serializer.data , "count":len(history)})

