import json

import httpx
import pytest

from discord_service.core_client import CoreClient
from discord_service.discord import Webhook
from discord_service.store import Store

OPEN = ("todo", "doing", "paused", "blocked", "review")


def task(i, due, status="todo", stop_reason=""):
    return {
        "id": i,
        "number": f"TASK-{i}",
        "title": f"할 일 {i}",
        "project": {"id": 1, "name": "학식 API", "team_id": 1},
        "assignee": {"id": 2, "display_name": "팀원", "discord_user_id": "111"},
        "status": status,
        "priority": 5,
        "due_date": due,
        "stop_reason": stop_reason,
        "next_action": "",
        "url": f"http://pm/tasks/{i}",
    }


def weekly_data(
    completed=(), reopened=(), due_this_week=(), overdue=(), blocked=(), by_project=None
):
    completed, reopened = list(completed), list(reopened)
    due_this_week, overdue, blocked = list(due_this_week), list(overdue), list(blocked)
    return {
        "team": {"id": 1, "name": "산돌이"},
        "period_start": "2026-08-31",
        "period_end": "2026-09-07",
        "completed": completed,
        "reopened": reopened,
        "due_this_week": due_this_week,
        "overdue": overdue,
        "blocked": blocked,
        "by_project": by_project
        if by_project is not None
        else [
            {
                "project": {"id": 1, "name": "학식 API", "status": "active"},
                "completed": len(completed),
                "reopened": len(reopened),
                "open": 2,
                "overdue": len(overdue),
                "blocked": len(blocked),
            }
        ],
        "counts": {
            "completed": len(completed),
            "reopened": len(reopened),
            "due_this_week": len(due_this_week),
            "overdue": len(overdue),
            "blocked": len(blocked),
            "open": 2,
            "review": 0,
            "no_due": 0,
        },
        "members": [{"id": 2, "display_name": "팀원", "discord_user_id": "111"}],
    }


class FakeCore:
    """core API 흉내. tasks dict를 바꾸면 응답이 바뀐다."""

    def __init__(
        self,
        tasks: list[dict],
        weekly: dict | None = None,
        webhook_urls: list[str] | None = None,
    ):
        self.tasks = {t["id"]: t for t in tasks}
        self.weekly_data = weekly
        self.status_reports = []
        self.webhook_urls = (
            ["https://discord.com/api/webhooks/1/aaa"] if webhook_urls is None else webhook_urls
        )
        self.webhook_status = 200  # 500으로 바꾸면 목록 조회가 실패한다
        self.webhook_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/tasks":
            items = [t for t in self.tasks.values() if t["status"] in OPEN]
            due_to = request.url.params.get("due_to")
            if due_to:
                items = [t for t in items if t["due_date"] and t["due_date"] <= due_to]
            return httpx.Response(
                200, json={"items": items, "total": len(items), "limit": 200, "offset": 0}
            )
        if path.startswith("/api/tasks/"):
            t = self.tasks.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=t) if t else httpx.Response(404, json={"detail": "x"})
        if path == "/api/reports/weekly":
            return httpx.Response(200, json=self.weekly_data)
        if path == "/api/integrations/discord/webhooks":
            self.webhook_calls += 1
            if self.webhook_status != 200:
                return httpx.Response(self.webhook_status, json={"detail": "x"})
            return httpx.Response(200, json={"urls": self.webhook_urls})
        if path.startswith("/api/integrations/"):
            self.status_reports.append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404)


class FakeHook:
    def __init__(self, statuses=None):
        self.sent = []
        self.payloads = []
        self.urls = []
        self.statuses = list(statuses or [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.payloads.append(payload)
        self.urls.append(str(request.url))
        self.sent.append(payload["content"])
        code = self.statuses.pop(0) if self.statuses else 204
        return httpx.Response(code, headers={"Retry-After": "0"} if code == 429 else {})


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.sqlite"))


@pytest.fixture
def fake_hook():
    return FakeHook()


def make_hook(fake: FakeHook) -> Webhook:
    return Webhook(
        "https://discord.com/api/webhooks/x/y",
        transport=httpx.MockTransport(fake.handler),
        sleep=lambda s: None,
    )


@pytest.fixture
def hook(fake_hook):
    return make_hook(fake_hook)


def make_core(fake: FakeCore) -> CoreClient:
    return CoreClient("http://core", "pm_test", transport=httpx.MockTransport(fake.handler))
