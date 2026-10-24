from django.urls import path

from apps.attendance.views import days, punch

urlpatterns = [
    path("punch", punch.web_punch),
    path("today", punch.today),
    path("days/daily", days.daily),
    path("days", days.period_days),
    path("recalculate", days.recalculate_view),
    path("punches", punch.punches),
    path("punches/<uuid:uuid>", punch.delete_punch),
]
