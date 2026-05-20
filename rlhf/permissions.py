from rest_framework.permissions import BasePermission


class IsStaff(BasePermission):
    """Allow only authenticated users with ``is_staff = True``."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_staff)
