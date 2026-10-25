from django.urls import path

from . import views

urlpatterns = [
    path("inbox/", views.inbox, name="notifications-inbox"),
    path("unread-count/", views.unread_count, name="notifications-unread-count"),
    path("read/", views.read, name="notifications-read"),
    path("read-all/", views.read_all, name="notifications-read-all"),
    path("send/", views.send, name="notifications-send"),
    path("sent/", views.sent, name="notifications-sent"),
    path("sent/<uuid:uuid>/recipients/", views.sent_recipients, name="notifications-sent-recipients"),
    path("sent/<uuid:uuid>/retract/", views.sent_retract, name="notifications-sent-retract"),
]
