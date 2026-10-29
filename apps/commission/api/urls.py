from django.urls import path , include
from apps.commission.views import (
    UserCommissionDetailsAPI , 
    BasicRecordAPI , 
    CoinChangerAPI , 
    SubscriptionAPI ,
    CommissionAPI
    )
from ..views.basic import get_users_with_has_basic , get_users_with_basic_commission

urlpatterns = [
    path('user-commission-details',UserCommissionDetailsAPI.as_view()),
    path('users-basic',get_users_with_has_basic),
    path('users-commission',get_users_with_basic_commission),
    path('basic-details',BasicRecordAPI.as_view()),
    path('coin-changer',CoinChangerAPI.as_view()),
    path('subscription',SubscriptionAPI.as_view()),
    path('salary',CommissionAPI.as_view()),
]
