import json

import pytest

from mcp_server import server as s
from mcp_server.auth import current_token
from mcp_server.core_client import CoreError

TOOL_NAMES = {
    "list_teams",
    "list_projects",
    "get_project",
    "list_tasks",
    "get_task",
    "create_task",
    "update_task",
    "transition_task",
    "append_note",
    "get_team_status",
    "get_weekly_report_data",
    "list_members",
    "search",
    "fetch",
}


def fn(name):
    """@mcp.tool()이 FunctionTool을 돌려주면 .fn으로 원함수를 꺼낸다."""
    obj = getattr(s, name)
    return getattr(obj, "fn", obj)


def last_body(fake):
    return json.loads(fake.calls[-1][3])


def test_list_teams_sends_bearer_and_source(fake_core, with_token):
    out = fn("list_teams")()
    assert out["teams"][0]["name"] == "산돌이"
    headers = fake_core.calls[-1][2]
    assert headers["authorization"] == "Bearer pm_good"
    assert headers["x-source"] == "mcp"


def test_tool_without_token_fails(fake_core):
    with pytest.raises(PermissionError):
        fn("list_teams")()


def test_bad_token_message(fake_core):
    tok = current_token.set("pm_bad")
    try:
        with pytest.raises(CoreError) as e:
            fn("list_teams")()
        assert "유효하지 않습니다" in str(e.value)
    finally:
        current_token.reset(tok)


def test_transition_done_matches_api(fake_core, with_token):
    out = fn("transition_task")(1, "done", version=1)
    assert out["status"] == "done"
    assert out["version"] == 2
    assert last_body(fake_core) == {"status": "done", "version": 1, "reason": ""}


def test_transition_blocked_needs_reason(fake_core, with_token):
    with pytest.raises(CoreError) as e:
        fn("transition_task")(1, "blocked", version=1)
    assert "막힘 사유" in str(e.value)
    out = fn("transition_task")(1, "blocked", version=1, reason="서류")
    assert out["status"] == "blocked"
    assert out["stop_reason"] == "서류"


def test_update_conflict_message(fake_core, with_token):
    with pytest.raises(CoreError) as e:
        fn("update_task")(1, version=99, priority=8)
    msg = str(e.value)
    assert "먼저 수정했습니다" in msg
    assert "version=1" in msg


def test_update_clear_due(fake_core, with_token):
    fn("update_task")(1, version=1, clear_due_date=True, no_due_reason="미정")
    body = last_body(fake_core)
    assert body["due_date"] is None
    assert body["no_due_reason"] == "미정"


def test_append_note_appends_with_version(fake_core, with_token):
    fn("append_note")(1, "첫 메모")
    body = last_body(fake_core)
    assert body["notes"] == "첫 메모"
    assert body["version"] == 1

    fn("append_note")(1, "둘째")
    body = last_body(fake_core)
    assert body["notes"] == "첫 메모\n둘째"
    assert body["version"] == 2

    with pytest.raises(CoreError):
        fn("append_note")(1, "   ")


def test_create_task_idempotency_header(fake_core, with_token):
    fn("create_task")(1, "새 일", due_date="2026-09-20", request_id="r1")
    method, path, headers, content = fake_core.calls[-1]
    assert headers["idempotency-key"] == "r1"
    assert json.loads(content)["priority"] == 5


def test_search_fetch_shape(fake_core, with_token):
    first = fn("search")("메뉴")["results"][0]
    assert {"id", "title", "url"} <= set(first)
    doc = fn("fetch")("1")
    assert {"id", "title", "text", "url", "metadata"} <= set(doc)
    assert "진행 메모" in doc["text"]


async def test_tool_names_registered():
    tools = await s.mcp.list_tools()
    assert {t.name for t in tools} == TOOL_NAMES
    assert len(TOOL_NAMES) == 14
