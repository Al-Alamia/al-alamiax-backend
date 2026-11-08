from django.urls import path

from . import views

urlpatterns = [
    path("heartbeat", views.heartbeat_view),
    path("access", views.access),
    path("events", views.events),
    path("presence", views.presence),
    path("users/<uuid:user_uuid>", views.user_detail),
]
