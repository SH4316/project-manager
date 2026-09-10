from django.contrib import admin

from tasks.admin import ReadOnlyAdmin

from .models import Project


@admin.register(Project)
class ProjectAdmin(ReadOnlyAdmin):
    """조회 전용. 이유는 tasks.admin.ReadOnlyAdmin 참고."""

    list_display = ("name", "team", "status", "is_archived")
    list_filter = ("team", "status", "is_archived")
    filter_horizontal = ("owners",)
