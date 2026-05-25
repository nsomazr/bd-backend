from rest_framework.permissions import AllowAny, BasePermission

from accounts.visitors import require_actor, resolve_actor


class AllowAnyWithVisitor(BasePermission):
    """Public endpoints that still resolve optional JWT + visitor id."""

    def has_permission(self, request, view):
        request.actor = resolve_actor(request)
        return True


class RequiresUserOrVisitor(BasePermission):
    """Authenticated user OR valid X-Visitor-Id header."""

    def has_permission(self, request, view):
        request.actor = resolve_actor(request)
        try:
            require_actor(request.actor)
        except Exception:
            return False
        return True
