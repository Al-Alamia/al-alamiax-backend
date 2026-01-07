from django.urls import path , include
from .views import total_treasury , AdvancesAPIView , OutcomeAPIView , IncomeAPIView , my_notification , seen_notification , NotificationAPIView

urlpatterns = [
    path('total-treasury',total_treasury) ,
    path('advance',AdvancesAPIView.as_view()) ,
    path('treasury-income',IncomeAPIView.as_view()) ,
    path('treasury-outcome',OutcomeAPIView.as_view()) ,
    path('my-notification',my_notification) ,
    path('seen-notification',seen_notification) ,
    path('notifications',NotificationAPIView.as_view()) ,
]
