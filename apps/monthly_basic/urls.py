from django.urls import path

from . import views

urlpatterns = [
    path("", views.basic_list),
    path("users/<uuid:uuid>", views.basic_detail),
    path("users/<uuid:uuid>/give", views.give),
    path("users/<uuid:uuid>/ungive", views.ungive),
    path("close", views.close),
    path("reopen", views.reopen),
]
