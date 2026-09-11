from django.contrib import admin

from .models import ChangeLog, Link, Task


class ReadOnlyAdmin(admin.ModelAdmin):
    """조회 전용 admin.

    GUIDE-00 §3: `Task`·`Project`는 `services.py` 밖에서 `save()`·`update()`로 바꾸지 않는다.
    admin 변경 폼은 그 규칙을 어긴다. 통과하는 수정은 ChangeLog도 version도 남기지 않아
    주간 보고(`reports.weekly`가 ChangeLog에서 완료 수를 센다)와 낙관적 잠금을 조용히 망가뜨리고,
    `status=done`처럼 DB 제약이 막는 조합은 500이 된다. 그래서 쓰기를 닫는다.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Task)
class TaskAdmin(ReadOnlyAdmin):
    list_display = ("id", "title", "project", "assignee", "status", "priority", "due_date")
    list_filter = ("status", "project__org")
    search_fields = ("title",)


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
