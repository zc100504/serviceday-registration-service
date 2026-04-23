from rest_framework import serializers
from .models import Registration


class RegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Registration
        fields = ['id', 'employee_id', 'ngo_id', 'registered_at', 'completed']
        read_only_fields = ['id', 'registered_at']