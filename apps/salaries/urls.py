from django.urls import path

from . import views

urlpatterns = [
    path("", views.salary_list),
    path("give-all", views.give_all),
    path("mine", views.mine),
    path("users/<uuid:uuid>", views.salary_detail),
    path("users/<uuid:uuid>/history", views.history),
    path("users/<uuid:uuid>/give", views.give),
    path("users/<uuid:uuid>/ungive", views.ungive),
    path("users/<uuid:uuid>/overrides/<str:part_key>", views.override),
]
