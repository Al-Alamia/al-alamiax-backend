import pandas as pd
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST
from rest_framework.request import Request
from apps.users.models import Lead , User 
from apps.commission.models import Additional , Team
from apps.users.serializers import  LeadSerializer
from apps.users.views import IsAuthenticated , IsOwner , IsSuperUser
from django.db import connection 
import datetime , numpy,calendar
from django.db.models import Q , Case , Count
from datetime import date
from django.db.models.functions import TruncDate
from utils.parsers import parse_date


DATE_FORMATS = [
    "%Y-%m-%d - %H:%M", # 2024-09-08 - 06:35
    "%Y-%m-%d %H:%M:%S", # 2024-09-08 06:35
    "%m/%d/%Y %H:%M", # 8/28/2024 11:48
]



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_sheet(request: Request):
        
    if 'file' not in request.FILES:
        return Response({"error": "No file uploaded"}, status=HTTP_400_BAD_REQUEST)

    file = request.FILES['file']
    
    try:
        df = pd.read_excel(file)
        df = df[["Market","Phone","Date"]]
    except Exception as e:
        return Response({"error": f"Error reading Excel file: {str(e)}"}, status=HTTP_400_BAD_REQUEST)

    if 'Phone' not in df.columns or 'Market' not in df.columns:
        return Response({"error": "Excel file must contain 'Phone' and 'Market' columns"}, status=HTTP_400_BAD_REQUEST)
    
    
    crm_names = User.objects.filter(~Q(crm_username="") & ~Q(crm_username=None) ).values_list("crm_username",flat=True)
    
    df = df[df["Market"].isin(crm_names)]
    
    
    df["Date"] = df["Date"].map(lambda date : parse_date(str(date), DATE_FORMATS) )
    
    
    df["Phone"] = df["Phone"].map(str)
    
    
    df["Market"] = df["Market"].map(lambda crm_username : User.objects.filter(crm_username=crm_username).first() )
    
    
    df["Market"] = df["Market"].map(lambda user : str(user.uuid).replace("-","") if user else numpy.nan)
    
    df.dropna(inplace=True)

    
    df.rename(columns={
        "Market" : "user_id",
        "Phone" :"phone"
    },inplace=True)
    
    

    # database_frame = pd.read_sql_query(str(Lead.objects.all().query),connection)
    
    # merge_columns = ['user_id', 'phone']

    # merged = df.merge(
    #     database_frame[merge_columns],
    #     on=merge_columns, 
    #     how='left', 
    #     indicator=True
    # )
    
    # df["Exist"] = merged['_merge'] == 'both'
    
    # print(df.head(20))
    # df.to_excel("testing.xlsx")
    response_data = {
        
        # "new_count": len(df[df["Exist"] == False]),
        # "old_count": len(df[df["Exist"] == True]),
        "total_count": len(df),
    }
    
    return Response(response_data, status=HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsOwner|IsSuperUser])
def save_upload(request:Request):

    if 'file' not in request.FILES:
        return Response({"error": "No file uploaded"}, status=HTTP_400_BAD_REQUEST)

    file = request.FILES['file']
    
    try:
        df = pd.read_excel(file)
        df = df[["Market","Phone","Date","Name"]]
    except Exception as e:
        return Response({"error": f"Error reading Excel file: {str(e)}"}, status=HTTP_400_BAD_REQUEST)

    if 'Phone' not in df.columns or 'Market' not in df.columns:
        return Response({"error": "Excel file must contain 'Phone' and 'Market' columns"}, status=HTTP_400_BAD_REQUEST)
    
    crm_names = User.objects.filter(~Q(crm_username="") & ~Q(crm_username=None) ).values_list("crm_username",flat=True)
    
    df = df[df["Market"].isin(crm_names)]


    df["Date"] = df["Date"].map(lambda date : parse_date(str(date), DATE_FORMATS)) #
    
    
    df["Phone"] = df["Phone"].map(str)
    
    
    df["Market"] = df["Market"].map(lambda crm_username : User.objects.filter(crm_username=crm_username).first() )
    
        
    database_frame = pd.read_sql_query(str(Lead.objects.all().query),connection)
    
    database_frame.rename(columns={
        "user_id" : "Market",
        "phone" : "Phone" ,
    },inplace=True)
    
    # database_frame["Market"] = database_frame["Market"].map(lambda crm_username : User.objects.filter(uuid=crm_username).first())

    
    # merge_columns = ['Market', 'Phone']

    # merged = df.merge(
    #     database_frame[merge_columns],
    #     on=merge_columns, 
    #     how='left', 
    #     indicator=True
    # )
    
    # df["Exist"] = merged['_merge'] == 'both'
    
    objects = [ 
            Lead(
                user = row["Market"] ,
                phone = row["Phone"] ,
                name = getattr(row,"Name",""),
                date =  row["Date"] ,
                project = getattr(row["Market"],"project",None),
                ) 
               for index , row in df.iterrows()
               if isinstance(row["Market"],User)
               ]
    leads = Lead.objects.bulk_create(objects,ignore_conflicts=True)
    return Response(LeadSerializer(leads,many=True).data, status=HTTP_200_OK)





@api_view(["POST"])
@permission_classes([IsAuthenticated])
def user_leads(request:Request):
    user_uuid = request.query_params.get("user_uuid")
    month = request.query_params.get("month")
    year = request.query_params.get("year")
    last_day = calendar.monthrange(int(year), int(month))[1]
    date_range = (
        date(int(year),int(month),1) ,
        date( int(year) , int(month) , last_day) + datetime.timedelta(days=1)
    )
    leads = Lead.objects.filter(date__range = date_range ,user__uuid = user_uuid)        
    lead_counts = (
        leads
        .annotate(day=TruncDate('date'))
        .values('day')
        .annotate(lead_count=Count('uuid'))
        .filter(lead_count__gte=5)
        .count()
    )
    
    teams_details = []
    teams = Team.objects.filter(leader__uuid= user_uuid)
    for team in teams:
        teams_details.append({
            "name" : team.name,
            "total" : Lead.objects.filter(date__range = date_range ,user__in = team.agents.all() ).count()
        })
    
    
    additional = Additional.objects.first()
    return Response({"total":leads.count(),"plus":lead_counts,"teams": teams_details, "plus_value":lead_counts * getattr(additional,"plus",30)  , "plus_price" : getattr(additional,"plus",30), "american_leads_price": getattr(additional,"american_leads",30)})




