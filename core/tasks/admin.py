from django.contrib import admin

from .models import ChangeLog, Link, Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "project", "assignee", "status", "priority", "due_date")
    list_filter = ("status", "project__team")
    search_fields = ("title",)
    readonly_fields = ("version", "completed_at", "stopped_at")


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "target_type",
        "target_id",
        "field",
        "old_value",
        "new_value",
        "actor",
        "source",
    )
    list_filter = ("target_type", "source")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Link)
