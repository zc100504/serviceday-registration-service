from rest_framework import serializers
from .models import Registration


class RegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Registration
        fields = ['id', 'employee_id', 'ngo_id', 'registered_at', 'completed']
        read_only_fields = ['id', 'registered_at', 'employee_id', 'completed']

    def validate_ngo_id(self, value):
        """Topic 7.4a — Input validation"""
        if value <= 0:
            raise serializers.ValidationError("Activity ID must be a positive number.")
        return value


class RegisterRequestSerializer(serializers.Serializer):
    """Validates incoming registration requests"""
    ngo_id = serializers.IntegerField()

    def validate_ngo_id(self, value):
        if value <= 0:
            raise serializers.ValidationError("Activity ID must be a positive number.")
        return value


class SwitchRequestSerializer(serializers.Serializer):
    """Validates incoming switch requests"""
    ngo_id = serializers.IntegerField()

    def validate_ngo_id(self, value):
        if value <= 0:
            raise serializers.ValidationError("Activity ID must be a positive number.")
        return value