from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import GuestVisitor, User


@admin.register(GuestVisitor)
class GuestVisitorAdmin(admin.ModelAdmin):
    list_display = (
        "visitor_key",
        "location_label",
        "visit_count",
        "last_ip",
        "linked_user",
        "last_seen",
    )
    search_fields = ("visitor_key", "country", "city", "last_ip", "linked_user__email")
    readonly_fields = (
        "visitor_key",
        "first_seen",
        "last_seen",
        "visit_count",
        "first_ip",
        "last_ip",
        "country",
        "region",
        "city",
        "user_agent",
    )


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "name", "is_staff", "is_active", "date_joined")
    search_fields = ("email", "name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("name",)}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "password1", "password2"),
            },
        ),
    )
