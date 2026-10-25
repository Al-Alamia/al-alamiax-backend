from django.urls import path , include
from .views import total_treasury , AdvancesAPIView , OutcomeAPIView , IncomeAPIView

urlpatterns = [
    path('total-treasury',total_treasury) ,
    path('advance',AdvancesAPIView.as_view()) ,
    path('treasury-income',IncomeAPIView.as_view()) ,
    path('treasury-outcome',OutcomeAPIView.as_view()) ,
]
