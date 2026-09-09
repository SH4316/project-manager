from django.contrib import admin

from .models import Invite, Membership, Team


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    inlines = [MembershipInline]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("team", "created_by", "expires_at", "revoked_at", "use_count")
    readonly_fields = ("token",)
