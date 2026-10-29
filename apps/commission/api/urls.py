from django.urls import path
from apps.commission.views import BasicRecordAPI, CommissionAPI

urlpatterns = [
    path('basic-details',BasicRecordAPI.as_view()),
    path('salary',CommissionAPI.as_view()),
]
