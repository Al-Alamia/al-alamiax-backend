from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.purposes.views import PurposeViewSet

router = DefaultRouter()
router.register(r'purposes', PurposeViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
