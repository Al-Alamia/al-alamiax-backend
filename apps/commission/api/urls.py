from django.urls import path , include
from apps.commission.views import (
    UserCommissionDetailsAPI , 
    DeductionRulesAPI , 
    TargetSlicesAPI , 
    BasicRecordAPI , 
    CoinChangerAPI , 
    TeamAPI , 
    SubscriptionAPI ,
    CommissionAPI
    )
from ..views.basic import get_users_with_has_basic , get_users_with_basic_commission
from ..views.targets import get_target_slices 

urlpatterns = [
    path('user-commission-details',UserCommissionDetailsAPI.as_view()),
    path('deduction-rules',DeductionRulesAPI.as_view()),
    path('target-slices',TargetSlicesAPI.as_view()),
    path('users-basic',get_users_with_has_basic),
    path('users-commission',get_users_with_basic_commission),
    path('basic-details',BasicRecordAPI.as_view()),
    path('coin-changer',CoinChangerAPI.as_view()),
    path('subscription',SubscriptionAPI.as_view()),
    path('salary',CommissionAPI.as_view()),
    path('team',TeamAPI.as_view()),
    path('targets',get_target_slices),
]
