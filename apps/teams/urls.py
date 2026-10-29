from django.urls import path

from . import views

urlpatterns = [
    path("teams", views.teams),
    path("teams/<uuid:uuid>", views.team_detail),
    path("teams/<uuid:uuid>/members", views.team_members),
    path("plans", views.plans),
    path("plans/preview", views.plan_preview),
    path("plans/<uuid:uuid>", views.plan_detail),
    path("plans/<uuid:uuid>/versions/<str:month>", views.plan_version),
    path("meta", views.meta),
    path("my", views.my),
]
