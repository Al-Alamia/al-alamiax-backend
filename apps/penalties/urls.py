from django.urls import path

from . import views

urlpatterns = [
    path("types", views.types),
    path("types/<uuid:uuid>", views.type_detail),
    path("penalties", views.penalty_list),
    path("penalties/meta", views.meta),
    path("penalties/targets", views.targets),
    path("penalties/period-total", views.period_total_view),
    path("penalties/<uuid:uuid>/void", views.void),
]
