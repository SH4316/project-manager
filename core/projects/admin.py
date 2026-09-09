from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "status", "is_archived")
    list_filter = ("team", "status", "is_archived")
    filter_horizontal = ("owners",)
    readonly_fields = ("version", "archived_at")
