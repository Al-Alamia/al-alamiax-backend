from django.urls import path

from . import views

urlpatterns = [
    path("balance", views.balance),
    path("groups/breakdown", views.breakdown),
    path("entries", views.entries),
    path("entries/<uuid:pk>/reverse", views.entry_reverse),
    path("groups", views.groups),
    path("groups/<uuid:pk>", views.group_detail),
    path("import/preview", views.import_preview),
    path("import", views.import_batches),
    path("import/<uuid:pk>/reverse", views.import_reverse),
]
