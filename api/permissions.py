from rest_framework.permissions import BasePermission


def get_user_role(user):
    if not user or not user.is_authenticated:
        return None
    if not hasattr(user, "profile"):
        return None
    return user.profile.role


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) == "ADMIN"


class IsSupervisorRole(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) == "SUP"


class IsTechnicianRole(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) == "TECH"


class IsAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) in ["ADMIN", "SUP"]


class IsAnyProjectRole(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) in ["ADMIN", "SUP", "TECH"]