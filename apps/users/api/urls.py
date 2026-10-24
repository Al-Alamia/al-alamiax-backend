from django.urls import path , include
from apps.users.views.report_views import add_report , check_report , get_reports
from apps.users.views.authenticate import login , logout , token_refresh
from apps.users.views import (
    ProjectViewSet , 
    DepartmentViewSet , 
    UsersAPI ,
    ArrivingLeavingAPI ,
    LeadAPI ,
    ProfileAPI ,
    RequestAPI ,
    FingerPrintIDAPI,
     )
from apps.users.views.arrive_leave import arreive , leave , arrive_leave_details , test , MonthlyHistoryView
from apps.users.views.lead_pipeline import LeadViewSet
from apps.users.views.leads import upload_sheet , save_upload , user_leads


urlpatterns = [
    path('login',login ),
    path('logout',logout) ,
    path('token/refresh',token_refresh) ,
    path('arrive',arreive) ,
    path('leave',leave) , 
    path('arrive-leave-details',arrive_leave_details) , 
    path('user',UsersAPI.as_view()) ,
    path('project', ProjectViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('project/<uuid:uuid>', ProjectViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'})),
    path('department', DepartmentViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('department/<uuid:uuid>', DepartmentViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'})),
    path('arriving-leaving',ArrivingLeavingAPI.as_view()) ,
    path('arriving-leaving-list',MonthlyHistoryView.as_view()) ,
    path('leads', LeadViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('leads/me', LeadViewSet.as_view({'get': 'me'})),
    path('leads/stats', LeadViewSet.as_view({'get': 'stats'})),
    path('leads/assign', LeadViewSet.as_view({'post': 'assign'})),
    path('leads/assignable-agents', LeadViewSet.as_view({'get': 'assignable_agents'})),
    path('leads/delete-by-phones', LeadViewSet.as_view({'post': 'delete_by_phones'})),
    path('leads/<uuid:uuid>', LeadViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})),
    path('leads/<uuid:uuid>/updates', LeadViewSet.as_view({'get': 'updates'})),
    path('leads/<uuid:uuid>/notes', LeadViewSet.as_view({'post': 'notes'})),
    path('leads/<uuid:uuid>/status', LeadViewSet.as_view({'post': 'set_status'})),
    path('leads/<uuid:uuid>/return', LeadViewSet.as_view({'post': 'return_lead'})),
    path('leads/<uuid:uuid>/hide', LeadViewSet.as_view({'post': 'hide'})),
    path('leads/<uuid:uuid>/unhide', LeadViewSet.as_view({'post': 'unhide'})),
    path('lead',LeadAPI.as_view()) ,
    path('profile',ProfileAPI.as_view()) ,
    path('request',RequestAPI.as_view()) ,
    path('device-access',FingerPrintIDAPI.as_view()) ,
    path('upload-sheet',upload_sheet) ,
    path('save-upload',save_upload) ,
    path('user-leads',user_leads) ,
    
    path('add-report',add_report) ,
    path('check-report',check_report) ,
    path('get-reports',get_reports) ,

    path('test',test) ,
]
