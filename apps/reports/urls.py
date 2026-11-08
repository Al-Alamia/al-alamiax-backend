from django.urls import path

from . import views

urlpatterns = [
    path("access", views.access),
    path("my", views.my),
    path("submissions/<uuid:uuid>", views.submission_detail),
    path("types", views.types),
    path("types/options", views.type_options),
    path("types/<uuid:uuid>", views.type_detail),
    path("types/<uuid:uuid>/submit", views.submit),
    path("types/<uuid:uuid>/board", views.board),
]
