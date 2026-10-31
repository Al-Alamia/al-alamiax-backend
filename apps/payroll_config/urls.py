from django.urls import path

from . import views

urlpatterns = [
    path("salaries", views.salaries),
    path("salaries/<uuid:uuid>/<str:month>", views.salary_detail),
    path("rates", views.rates),
    path("rates/<str:month>/<str:currency>", views.rate_detail),
    path("department-rates", views.department_rates),
    path("department-rates/<uuid:uuid>/<str:month>", views.department_rates_detail),
    path("meta", views.meta),
]
