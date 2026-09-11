from django.contrib import admin

from .models import Invite, Organization, OrgMembership, Team, TeamMembership


class OrgMembershipInline(admin.TabularInline):
    model = OrgMembership
    extra = 0


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    inlines = [OrgMembershipInline]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "created_by", "created_at")
    inlines = [TeamMembershipInline]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("org", "created_by", "expires_at", "revoked_at", "use_count")
    readonly_fields = ("token",)
