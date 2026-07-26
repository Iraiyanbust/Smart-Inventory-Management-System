from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import User


def _role(user) -> str | None:
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "role", None)


class IsAuthenticatedRole(BasePermission):
    """Must be logged in and have a valid role attribute."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        role = _role(user)
        return role in {
            User.Role.ADMIN,
            User.Role.STORE_MANAGER,
            User.Role.INVENTORY_STAFF,
        }


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return _role(request.user) == User.Role.ADMIN


class IsStoreManager(BasePermission):
    def has_permission(self, request, view):
        return _role(request.user) == User.Role.STORE_MANAGER


class IsInventoryStaff(BasePermission):
    def has_permission(self, request, view):
        return _role(request.user) == User.Role.INVENTORY_STAFF


class IsAdminOrStoreManager(BasePermission):
    def has_permission(self, request, view):
        return _role(request.user) in {User.Role.ADMIN, User.Role.STORE_MANAGER}


class IsAdminOrInventoryStaff(BasePermission):
    def has_permission(self, request, view):
        return _role(request.user) in {User.Role.ADMIN, User.Role.INVENTORY_STAFF}


class ReadOnlyUnlessAdmin(BasePermission):
    """SAFE methods for authenticated staff; write requires admin."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return _role(request.user) in {
                User.Role.ADMIN,
                User.Role.STORE_MANAGER,
                User.Role.INVENTORY_STAFF,
            }
        return _role(request.user) == User.Role.ADMIN
