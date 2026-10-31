from django.urls import path

from . import views

urlpatterns = [
    path("", views.subscription_list),
    path("leads/<uuid:uuid>", views.lead_subscriptions),
    path("payments/<uuid:uuid>", views.payment_detail),
    path("<uuid:uuid>", views.subscription_detail),
    path("<uuid:uuid>/cancel", views.subscription_cancel),
    path("<uuid:uuid>/payments", views.subscription_payments),
]
