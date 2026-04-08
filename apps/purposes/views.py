from rest_framework import viewsets
from apps.purposes.models import Purpose
from apps.purposes.serializers import PurposeSerializer

class PurposeViewSet(viewsets.ModelViewSet):
    queryset = Purpose.objects.all()
    serializer_class = PurposeSerializer
