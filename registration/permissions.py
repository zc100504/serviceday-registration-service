from rest_framework.permissions import BasePermission


class IsEmployee(BasePermission):
    def has_permission(self, request, view):
        if not isinstance(request.user, dict):
            return False
        groups = request.user.get('groups', [])
        return 'Employee' in groups


class IsAdministrator(BasePermission):
    def has_permission(self, request, view):
        if not isinstance(request.user, dict):
            return False
        groups = request.user.get('groups', [])
        return 'Administrator' in groups


class IsEmployeeOrAdmin(BasePermission):
    def has_permission(self, request, view):
        if not isinstance(request.user, dict):
            return False
        groups = request.user.get('groups', [])
        return 'Employee' in groups or 'Administrator' in groups