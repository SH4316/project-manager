from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ApiToken, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "display_name", "discord_user_id", "is_active", "is_superuser")
    fieldsets = UserAdmin.fieldsets + (
        ("프로필", {"fields": ("display_name", "discord_user_id", "auto_pull_days")}),
    )


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("prefix", "user", "name", "scope", "created_at", "expires_at", "revoked_at")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")
