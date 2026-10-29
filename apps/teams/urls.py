from django.urls import path

from . import views

urlpatterns = [
    path("teams", views.teams),
    path("teams/<uuid:uuid>", views.team_detail),
    path("teams/<uuid:uuid>/members", views.team_members),
    path("meta", views.meta),
    path("my", views.my),
]
