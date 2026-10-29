from django.urls import path
from apps.commission.views import CommissionAPI

urlpatterns = [
    path('salary',CommissionAPI.as_view()),
]
