from datetime import timedelta

import pytest

from accounts.models import ApiToken
from api.models import IntegrationStatus
from common.dates import last_week_start, today_kst, week_bounds
from tasks.services import create_task

pytestmark = pytest.mark.django_db


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


def test_me(api, team):
    r = api.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["teams"][0]["role"] == "member"
    assert body["auto_pull_days"] == 5


def test_unauthenticated_401(client, member):
    assert client.get("/api/me").status_code == 401


def test_revoked_token_401(client, member):
    token, raw = ApiToken.issue(member, "t", "read")
    token.revoke()
    assert client.get("/api/me", headers=_h(raw)).status_code == 401


def test_read_token_cannot_write(client, read_token, task, team):
    body = {"status": "done", "version": task.version}
    r = client.post(
        f"/api/tasks/{task.pk}/transition",
        data=body,
        content_type="application/json",
        headers=_h(read_token),
    )
    assert r.status_code == 403
    assert client.get(f"/api/tasks/{task.pk}", headers=_h(read_token)).status_code == 200


def test_read_token_can_report_integration_status(client, read_token, member):
    r = client.post(
        "/api/integrations/discord/status",
        data={"ok": True, "detail": {}},
        content_type="application/json",
        headers=_h(read_token),
    )
    assert r.status_code == 204
    assert IntegrationStatus.objects.count() == 1


def test_list_tasks_filters_and_paging(api, project, member, team):
    for i in range(3):
        create_task(
            project=project,
            title=f"t{i}",
            actor=member,
            source="web",
            due_date=today_kst() + timedelta(days=i + 1),
        )
    r = api.get(f"/api/tasks?team={team.pk}&status=todo&limit=2&offset=0")
    assert r.json()["total"] == 3
    assert len(r.json()["items"]) == 2
    assert api.get("/api/tasks?status=bogus").status_code == 400
    assert api.get("/api/tasks?status=blocked").json()["total"] == 0


def test_create_task_defaults_and_idempotency(api, project, member):
    body = {
        "project_id": project.pk,
        "title": "새 일",
        "due_date": (today_kst() + timedelta(days=2)).isoformat(),
    }
    h = {"Idempotency-Key": "k1"}
    r1 = api.post("/api/tasks", body, headers=h)
    r2 = api.post("/api/tasks", body, headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["assignee"]["id"] == member.pk
    assert r1.json()["priority"] == 5


def test_create_task_validation(api, project):
    r = api.post("/api/tasks", {"project_id": project.pk, "title": "", "no_due_reason": "x"})
    assert r.status_code == 400
    assert "title" in r.json()["detail"]
    r = api.post("/api/tasks", {"project_id": project.pk, "title": "t", "priority": 11})
    assert r.status_code == 422


def test_patch_conflict_409_with_latest(api, task):
    assert api.patch(f"/api/tasks/{task.pk}", {"version": 1, "priority": 8}).status_code == 200
    r = api.patch(f"/api/tasks/{task.pk}", {"version": 1, "priority": 9})
    assert r.status_code == 409
    assert r.json()["latest"]["priority"] == 8
    assert r.json()["latest"]["version"] == 2


def test_patch_notes_no_version_bump(api, task):
    r = api.patch(f"/api/tasks/{task.pk}", {"version": 99, "notes": "메모"})
    assert r.status_code == 200
    assert r.json()["notes"] == "메모"
    assert r.json()["version"] == 1


def test_patch_checklist_replaces(api, task):
    r = api.patch(f"/api/tasks/{task.pk}", {"version": 1, "checklist": [{"text": "x"}]})
    assert r.json()["checklist_total"] == 1


def test_transition_done_via_api_matches_web(api, task):
    assert (
        api.post(f"/api/tasks/{task.pk}/transition", {"status": "doing", "version": 1}).status_code
        == 200
    )
    r = api.post(f"/api/tasks/{task.pk}/transition", {"status": "done", "version": 2})
    assert r.status_code == 200
    assert r.json()["completed_at"] is not None
    assert r.json()["stop_reason"] == ""
    history = api.get(f"/api/tasks/{task.pk}/history").json()
    assert history[-1]["source"] == "api"


def test_transition_blocked_via_api(api, task):
    r = api.post(f"/api/tasks/{task.pk}/transition", {"status": "blocked", "version": 1})
    assert r.status_code == 400
    assert "stop_reason" in r.json()["detail"]
    r = api.post(
        f"/api/tasks/{task.pk}/transition",
        {"status": "blocked", "reason": "서류", "version": 1},
    )
    assert r.status_code == 200
    assert r.json()["stop_reason"] == "서류"


def test_extend_endpoint(api, task):
    new = (today_kst() + timedelta(days=5)).isoformat()
    r = api.post(f"/api/tasks/{task.pk}/extend", {"due_date": new, "reason": "회의", "version": 1})
    assert r.status_code == 200
    assert r.json()["due_date"] == new
    assert r.json()["version"] == 2
    r = api.post(
        f"/api/tasks/{task.pk}/extend",
        {
            "due_date": (today_kst() + timedelta(days=1)).isoformat(),
            "reason": "x",
            "version": 2,
        },
    )
    assert r.status_code == 400
    assert "due_date" in r.json()["detail"]


def test_source_mcp_header_recorded(api, task):
    api.post(
        f"/api/tasks/{task.pk}/transition",
        {"status": "doing", "version": 1},
        headers={"X-Source": "mcp"},
    )
    history = api.get(f"/api/tasks/{task.pk}/history").json()
    assert history[-1]["source"] == "mcp"


def test_today_endpoints(api, task):
    body = api.get("/api/today").json()
    assert len(body["items"]) == 1
    assert body["items"][0]["auto_pulled"] is True

    body = api.delete(f"/api/today/{task.pk}").json()
    assert body["items"] == []
    assert body["counts"]["excluded"] == 1

    body = api.delete("/api/today/excluded").json()
    assert len(body["items"]) == 1

    body = api.post("/api/today", {"task_id": task.pk}).json()
    assert body["items"][0]["auto_pulled"] is False

    assert api.patch("/api/today/order", {"task_ids": [task.pk]}).status_code == 200
    assert api.patch("/api/today/settings", {"auto_pull_days": 4}).status_code == 400
    r = api.patch("/api/today/settings", {"auto_pull_days": 0})
    assert r.status_code == 200
    assert r.json()["auto_pull_days"] == 0


def test_project_owners_via_api(api, team, member, admin):
    r = api.post(
        "/api/projects",
        {"team_id": team.pk, "name": "챗봇", "owner_ids": [member.pk, admin.pk]},
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    assert len(r.json()["owners"]) == 2
    r = api.patch(f"/api/projects/{pid}", {"version": 1, "owner_ids": []})
    assert r.json()["owners"] == []
    assert api.patch(f"/api/projects/{pid}", {"version": 2, "owner_ids": [9999]}).status_code == 400


def test_weekly_endpoint(api, team):
    r = api.get(f"/api/reports/weekly?team={team.pk}")
    assert r.status_code == 200
    assert r.json()["period_start"] == last_week_start().isoformat()
    tuesday = week_bounds()[0] + timedelta(days=1)
    assert (
        api.get(f"/api/reports/weekly?team={team.pk}&week_start={tuesday.isoformat()}").status_code
        == 400
    )


def test_team_status_endpoint(api, team):
    r = api.get(f"/api/teams/{team.pk}/status")
    assert r.status_code == 200
    assert "counts" in r.json()


def test_invite_admin_only(client, api, team, admin):
    assert api.post(f"/api/teams/{team.pk}/invites", {"days": 7}).status_code == 400
    _, raw = ApiToken.issue(admin, "a", "write")
    r = client.post(
        f"/api/teams/{team.pk}/invites",
        data={"days": 7},
        content_type="application/json",
        headers=_h(raw),
    )
    assert r.status_code == 201
    assert "/join/" in r.json()["url"]
