from django.contrib.admin.views.decorators import staff_member_required
from django.core import serializers
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from accounts.models import User
from api.models import IntegrationStatus
from projects.models import Project
from tasks.models import ChangeLog, ChecklistItem, Link, Task, TodayItem
from teams.models import DiscordWebhook, Invite, Membership, Team


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})


@staff_member_required
def ops(request):
    return render(request, "ops.html", {"statuses": IntegrationStatus.objects.order_by("name")})


@staff_member_required
def export_json(request):
    parts = [
        serializers.serialize(
            "json",
            User.objects.all(),
            fields=("username", "display_name", "discord_user_id", "is_active", "auto_pull_days"),
        ),
        serializers.serialize("json", Team.objects.all()),
        serializers.serialize("json", Membership.objects.all()),
        serializers.serialize(
            "json",
            Invite.objects.all(),
            fields=("team", "expires_at", "revoked_at", "use_count"),
        ),
        # 초대 token과 같은 이유로 Webhook url은 빼고 내보낸다. 백업에 비밀을 담지 않는다.
        serializers.serialize(
            "json",
            DiscordWebhook.objects.all(),
            fields=("team", "name", "is_active", "created_at", "last_test_at", "last_test_ok"),
        ),
        serializers.serialize("json", Project.objects.all()),
        serializers.serialize("json", Task.objects.all()),
        serializers.serialize("json", ChecklistItem.objects.all()),
        serializers.serialize("json", TodayItem.objects.all()),
        serializers.serialize("json", Link.objects.all()),
        serializers.serialize("json", ChangeLog.objects.all()),
    ]
    body = "[" + ",".join(p[1:-1] for p in parts if len(p) > 2) + "]"
    resp = HttpResponse(body, content_type="application/json")
    resp["Content-Disposition"] = 'attachment; filename="export.json"'
    return resp
