from rest_framework import serializers
from apps.purposes.models import Purpose

class PurposeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Purpose
        fields = '__all__'
