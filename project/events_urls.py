from django.urls import path

from apps.notifications.stream import notification_stream

urlpatterns = [path("api/notifications/stream", notification_stream)]
