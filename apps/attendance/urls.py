from django.urls import path

from apps.attendance.views import punch

urlpatterns = [
    path("punch", punch.web_punch),
    path("today", punch.today),
    path("punches", punch.punches),
    path("punches/<uuid:uuid>", punch.delete_punch),
]
