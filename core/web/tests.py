from datetime import timedelta

import pytest

from accounts.models import User
from common.dates import fmt_md, today_kst
from tasks.models import Task, TodayItem

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


@pytest.fixture
def logged(client, member):
    client.login(username="member1", password="pw12345678")
    return client


def test_root_redirects(client, member):
    assert client.get("/").headers["Location"] == "/login"
    client.login(username="member1", password="pw12345678")
    assert client.get("/").headers["Location"] == "/today"


def test_today_page_renders(logged, team, project, task):
    body = logged.get("/today").content.decode()
    assert "오늘 태스크" in body
    assert "빠른 추가" in body


def test_quick_add_creates_task_in_today(logged, project, member):
    r = logged.post(
        "/today/quick",
        {
            "title": "빠른 일",
            "project": project.pk,
            "priority": 5,
            "due_date": (today_kst() + timedelta(days=1)).isoformat(),
            "idem": "q1",
        },
        headers=HX,
    )
    assert r.status_code == 204
    assert r.headers["HX-Redirect"] == "/today"
    item = TodayItem.objects.get(user=member)
    assert item.excluded is False


def test_status_change_returns_row(logged, task):
    r = logged.post(f"/tasks/{task.pk}/status", {"status": "doing", "version": 1}, headers=HX)
    assert r.status_code == 200
    assert f'id="task-{task.pk}"' in r.content.decode()
    assert "task-updated" in r.headers["HX-Trigger"]
    task.refresh_from_db()
    assert task.status == "doing"


def test_status_blocked_without_reason_shows_error(logged, task):
    r = logged.post(f"/tasks/{task.pk}/status", {"status": "blocked", "version": 1}, headers=HX)
    assert r.status_code == 200
    assert "막힘 사유" in r.content.decode()
    task.refresh_from_db()
    assert task.status == "todo"


def test_status_change_conflict_shows_message(logged, task):
    logged.post(f"/tasks/{task.pk}/status", {"status": "doing", "version": 1}, headers=HX)
    r = logged.post(f"/tasks/{task.pk}/status", {"status": "review", "version": 1}, headers=HX)
    assert "먼저 수정했습니다" in r.content.decode()


def test_panel_contains_sections(logged, task):
    body = logged.get(f"/tasks/{task.pk}/panel").content.decode()
    for needle in ("변경 이력", 'id="checklist"', "진행 메모", "목표일"):
        assert needle in body


def test_text_autosave(logged, task):
    r = logged.post(f"/tasks/{task.pk}/text/notes", {"value": "메모"}, headers=HX)
    assert r.status_code == 204
    assert r.headers["HX-Trigger"] == "saved"
    task.refresh_from_db()
    assert task.notes == "메모"
    assert task.version == 1
    assert logged.post(f"/tasks/{task.pk}/text/title", {"value": ""}, headers=HX).status_code == 400


def test_stop_reason_confirm_block(logged, task):
    r = logged.post(
        f"/tasks/{task.pk}/stop-reason",
        {"reason": "서류", "version": 1, "confirm_block": "1"},
        headers=HX,
    )
    assert r.status_code == 200
    task.refresh_from_db()
    assert task.status == "blocked"
    assert "서류" in r.content.decode()
    assert "task-changed" in r.headers["HX-Trigger"]


def test_extend_from_panel(logged, task):
    new = today_kst() + timedelta(days=5)
    r = logged.post(
        f"/tasks/{task.pk}/extend",
        {"due_date": new.isoformat(), "reason": "회의", "version": 1},
        headers=HX,
    )
    assert r.status_code == 200
    assert fmt_md(new) in r.content.decode()
    task.refresh_from_db()
    assert task.due_date == new


def test_project_dialog_and_create(client, team, admin):
    client.login(username="admin1", password="pw12345678")
    body = client.get(f"/projects/new?team={team.pk}", headers=HX).content.decode()
    assert "<form" in body
    assert "프로젝트 만들기" in body
    r = client.post(
        "/projects/new",
        {"team": team.pk, "name": "챗봇", "status": "active", "owners": [admin.pk]},
        headers=HX,
    )
    assert r.status_code == 204
    assert "/projects/" in r.headers["HX-Redirect"]
    r = client.post("/projects/new", {"team": team.pk, "status": "active"}, headers=HX)
    assert r.status_code == 200
    assert "이름을 입력하세요" in r.content.decode()


def test_project_inline_task_create(logged, project, member):
    r = logged.post(
        f"/projects/{project.pk}/tasks",
        {
            "title": "인라인",
            "assignee": member.pk,
            "priority": 5,
            "due_date": (today_kst() + timedelta(days=2)).isoformat(),
            "idem": "i1",
        },
        headers=HX,
    )
    assert r.status_code == 204
    assert "#task-" in r.headers["HX-Redirect"]
    t = Task.objects.get(title="인라인")
    assert t.assignee == member


def test_me_team_view_read_only(logged, task):
    body = logged.get("/me?member=0").content.decode()
    assert "보기 전용" in body
    assert "disabled" in body


def test_team_page_renders(logged, team, project):
    body = logged.get(f"/teams/{team.pk}").content.decode()
    assert "미완료" in body
    assert project.name in body
    assert "새 프로젝트" in body


def test_signup_then_no_team_message(client):
    r = client.post(
        "/signup",
        {
            "username": "newbie",
            "display_name": "새사람",
            "password1": "verysecret123",
            "password2": "verysecret123",
        },
    )
    assert r.status_code == 302
    assert r.headers["Location"] == "/today"
    assert "초대 링크" in client.get("/today").content.decode()


def test_ops_requires_staff(client, member):
    client.login(username="member1", password="pw12345678")
    assert client.get("/ops").status_code in (302, 403)
    User.objects.filter(pk=member.pk).update(is_staff=True, is_superuser=True)
    assert client.get("/ops").status_code == 200


def test_export_json_has_no_password(client, member, task):
    User.objects.filter(pk=member.pk).update(is_staff=True, is_superuser=True)
    client.login(username="member1", password="pw12345678")
    r = client.get("/ops/export.json")
    assert r.status_code == 200
    assert "password" not in r.content.decode()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_token_shown_once(logged):
    r = logged.post("/settings/tokens", {"name": "t", "scope": "read"})
    assert r.status_code == 302
    assert "pm_" in logged.get("/settings/tokens").content.decode()
    assert "pm_" not in logged.get("/settings/tokens").content.decode()


def test_schedule_card_is_scoped_to_team_membership(logged, task, project, member):
    """일정 카드도 팀 범위를 따른다. 팀에서 빠지면 마감이 달력에 남지 않는다."""
    from teams.models import Membership

    body = logged.get("/today?schedule=1&cal=month").content.decode()
    assert task.title in body

    Membership.objects.filter(team=project.team, user=member).delete()
    body = logged.get("/today?schedule=1&cal=month").content.decode()
    assert task.title not in body


def test_non_numeric_ids_are_404_not_500(logged, project):
    """쿼리·경로의 id가 숫자가 아니면 404다. filter(pk="abc")는 ValueError -> 500이 된다."""
    assert logged.get("/projects/new?team=abc").status_code == 404
    assert logged.post("/projects/new", {"team": "abc", "name": "x"}, headers=HX).status_code == 404


def test_weird_digit_query_params_do_not_crash(logged, task):
    """isdigit()은 '²'에 True지만 int()는 실패한다. isdecimal()로 막아야 한다."""
    assert logged.get("/search?q=²").status_code == 200
    assert logged.get("/me?member=²").status_code == 200
    assert logged.get("/me?project=²").status_code == 200


def test_duplicate_discord_id_shows_field_error(client, admin, member):
    """unique=True인 discord_user_id 중복은 IntegrityError(500)가 아니라 폼 오류여야 한다."""
    client.login(username="admin1", password="pw12345678")
    r = client.post("/settings/profile", {"display_name": "관리자", "discord_user_id": "111"})
    assert r.status_code == 200
    assert "이미 쓰는" in r.content.decode()
    admin.refresh_from_db()
    assert admin.discord_user_id is None
