# 구현 지시서 01-5: core — 테스트와 완료 체크 (Step 7)

이전: [01-4](GUIDE-01-core-4-web.md). 테스트는 pytest-django 하나로 쓴다. 아래 테스트 **이름과 검증 내용을 그대로** 구현한다. 모두 통과해야 core가 완료다.

개정 2026-09-10: 상태 7개·멈춤 사유·중요도 정수·`update_text`·`extend_due`·오늘 자동 담기·`me_view`·프로젝트 관리자 여러 명·댓글 삭제에 맞춰 목록을 바꿨다.

---

## 7.1 `core/conftest.py`

```python
from datetime import timedelta

import pytest

from accounts.models import ApiToken, User
from common.dates import today_kst
from projects.services import create_project
from tasks.services import create_task
from teams.models import Membership
from teams.services import create_team


@pytest.fixture
def admin(db):
    return User.objects.create_user("admin1", password="pw12345678", display_name="관리자")


@pytest.fixture
def member(db):
    return User.objects.create_user("member1", password="pw12345678", display_name="팀원", discord_user_id="111")


@pytest.fixture
def outsider(db):
    return User.objects.create_user("outsider", password="pw12345678", display_name="외부인")


@pytest.fixture
def team(admin, member):
    t = create_team("산돌이", "학생 챗봇 서비스", admin)
    Membership.objects.create(team=t, user=member, role="member")
    return t


@pytest.fixture
def project(team, admin):
    return create_project(team=team, name="학식 API", actor=admin, owners=[admin], status="active")


@pytest.fixture
def task(project, member):
    return create_task(
        project=project, title="메뉴 누락 개선", actor=member, source="web",
        due_date=today_kst() + timedelta(days=3),
    )


@pytest.fixture
def write_token(member):
    _, raw = ApiToken.issue(member, "t", "write")
    return raw


@pytest.fixture
def read_token(member):
    _, raw = ApiToken.issue(member, "r", "read")
    return raw


@pytest.fixture
def api(client, write_token):
    """Bearer 인증이 붙은 간단한 API 클라이언트."""

    class Api:
        def _h(self, extra=None):
            h = {"Authorization": f"Bearer {write_token}"}
            h.update(extra or {})
            return h

        def get(self, url, **kw):
            return client.get(url, headers=self._h(kw.pop("headers", None)), **kw)

        def post(self, url, data=None, **kw):
            return client.post(url, data=data, content_type="application/json", headers=self._h(kw.pop("headers", None)), **kw)

        def patch(self, url, data=None, **kw):
            return client.patch(url, data=data, content_type="application/json", headers=self._h(kw.pop("headers", None)), **kw)

        def delete(self, url, **kw):
            return client.delete(url, headers=self._h(kw.pop("headers", None)), **kw)

    return Api()
```

`client.post(..., data=dict, content_type="application/json")`은 Django 테스트 클라이언트가 dict를 JSON으로 직렬화한다. `date` 객체는 넣지 말고 `isoformat()` 문자열로 넣는다. 웹 뷰를 HTMX 요청으로 부를 때는 `headers={"HX-Request": "true"}`를 준다.

---

## 7.1a `core/accounts/tests.py`

| 테스트 | 검증 |
|---|---|
| `test_display_name_truncated_from_long_username` | 120자 username으로 `create_user` → `display_name`이 50자. (자르지 않으면 Postgres에서 `DataError`) |

---

## 7.2 `core/teams/tests.py`

| 테스트 | 검증 |
|---|---|
| `test_create_team_makes_creator_admin` | `create_team` 후 `is_admin(admin, team)` 참 |
| `test_join_by_token_creates_membership_and_counts` | `create_invite(team, admin)` → `join_by_token(outsider, invite.token)` → `is_member` 참, `invite.use_count == 1`. 같은 사용자가 다시 join하면 `use_count`는 그대로 1 (B04) |
| `test_join_expired_or_revoked_invite_rejected` | `expires_at`을 과거로 바꾼 초대와 `revoke_invite`한 초대 각각 `ServiceError` (B04) |
| `test_member_cannot_create_invite` | `create_invite(team, member)` → `ServiceError` |
| `test_cannot_demote_last_admin` | `change_role(admin의 membership, "member", admin)` → `ServiceError` |
| `test_outsider_cannot_see_team_data_via_api` | outsider 토큰으로 `GET /api/teams/{team.id}` → 404, `GET /api/tasks` → `total == 0`, `GET /api/projects` → `[]` (A01) |
| `test_outsider_cannot_open_project_page` | outsider로 `client.login` 후 `GET /projects/{project.id}` → 404 (A01) |
| `test_join_page_requires_login_then_joins` | 비로그인 `GET /join/<token>` → 302 `/login?next=...`. 로그인 후 `POST /join/<token>` → 302 `/today`, 멤버십 생성 |

---

## 7.3 `core/projects/tests.py`

| 테스트 | 검증 |
|---|---|
| `test_project_without_owner_allowed` | `create_project(team=team, name="기타", actor=admin)` 성공, `owners.count() == 0`. `team_status(team)["projects_without_owner"]`에 포함 (B05) |
| `test_owner_must_be_member` | `owners=[outsider]` → `ServiceError` with key `owners` |
| `test_owners_many_and_logged` | `owners=[admin, member]`로 생성 → 2명. `update_project(p, {"owners": [member]}, actor=admin, expected_version=1)` → `owners`가 member 하나, ChangeLog(`project`, field `owners`) 1건, `version == 2` |
| `test_duplicate_name_in_team_rejected` | 같은 팀에 같은 이름 → `ServiceError` with key `name` |
| `test_invalid_status_rejected` | `status="closed"` → `ServiceError` with key `status` |
| `test_archive_blocked_by_open_tasks` | 미완료 task가 있는 project → `archive_project` `ServiceError`, `errors["tasks"]`에 `TASK-{id}` 포함 |
| `test_archive_and_restore` | task를 `done`으로 전이 후 `archive_project` → `is_archived` True, ChangeLog(`project`, `is_archived`) 1건. `restore_project` → False |
| `test_update_project_conflict` | `update_project(p, {"purpose": "a"}, expected_version=1)` 성공 후 같은 `expected_version=1`로 다시 → `ConflictError` |
| `test_member_cannot_archive` | `archive_project(project, actor=member)` → `ServiceError` |
| `test_project_stats_total_excludes_cancelled` | 태스크 3개를 각각 done·todo·cancelled로 만든 뒤 `project_stats(project)` → `total == 2`, `done == 1`, `open == 1` |
| `test_project_name_and_purpose_truncated_to_column_length` | `name="N"*150, purpose="P"*300`으로 생성 → 각각 100·200자. `update_project`도 같다. (자르지 않으면 Postgres에서 `DataError`) |
| `test_duplicate_check_uses_truncated_name` | `name="B"*100`으로 만든 뒤 `name="B"*150` → `ServiceError` key `name`. (검사와 저장이 다른 값을 쓰면 unique 제약에 걸려 500) |

---

## 7.4 `core/tasks/tests.py`

| 테스트 | 검증 |
|---|---|
| `test_create_defaults_assignee_to_actor` | `assignee` 없이 생성 → `assignee == actor`, `priority == 5`, ChangeLog `created` 1건 (A03) |
| `test_create_requires_title_and_reason_without_due` | 제목 빈 문자열 → `ServiceError` key `title`. `due_date=None, no_due_reason=""` → key `no_due_reason` |
| `test_create_rejects_non_member_assignee` | `assignee=outsider` → `ServiceError` key `assignee` (A03) |
| `test_assignee_is_required` | `update_task({"assignee": None})` → `ServiceError` key `assignee`, 담당자는 그대로 (A03) |
| `test_create_in_archived_project_rejected` | 보관된 프로젝트 → key `project` |
| `test_priority_range_1_to_10` | `priority=0`, `priority=11` → `ServiceError` key `priority`. `Task.objects.create(... priority=11 ...)` → `IntegrityError` |
| `test_db_constraint_doing_requires_due` | `Task.objects.create(... status="doing", due_date=None ...)` → `IntegrityError` (트랜잭션 안에서 `pytest.raises`) |
| `test_db_constraint_blocked_requires_reason` | `Task.objects.create(... status="blocked", stop_reason="" ...)` → `IntegrityError` |
| `test_transition_flow_records_completed_at_and_log` | todo→doing→done. `completed_at` not None, `version == 3`, ChangeLog `status` 2건, 마지막 `old_value="doing", new_value="done"` (A04) |
| `test_transition_to_doing_requires_due` | `due_date=None`(사유 있음)인 task를 `doing`으로 → `ServiceError` key `due_date`, 메시지가 `services.NO_DUE_FOR_DOING`과 같다 |
| `test_done_again_is_noop` | done 후 `transition(task, "done", expected_version=task.version)` → 같은 `completed_at`, 같은 `version`, ChangeLog 수 불변 (A06) |
| `test_reopen_clears_completed_at_reason_optional` | done → `todo`를 reason 없이 → 성공, `completed_at is None`, ChangeLog에 `field="completed_at"` 행이 있고 그 `old_value`가 이전 완료 시각 isoformat (A07). 다시 done → `todo` reason="다시 확인" → 마지막 `status` 로그의 `note == "다시 확인"` |
| `test_reopen_then_done_sets_new_completed_at` | 재개 후 다시 done → 새 `completed_at` > 이전 값 |
| `test_closed_can_only_reopen_to_todo_or_doing` | done → `review` → `ServiceError` key `status`. cancelled → `paused` → key `status` |
| `test_cancel_is_not_completion` | todo→cancelled. `completed_at is None`. `weekly()`의 `counts["completed"] == 0` |
| `test_transition_blocked_requires_reason_paused_optional` | doing→blocked reason 없음 → key `stop_reason`. reason="서류 대기" → `status == "blocked"`, `stop_reason == "서류 대기"`, `stopped_at` not None. todo→paused reason 없음 → 성공, `stop_reason == ""`, `stopped_at` not None |
| `test_blocked_to_paused_keeps_reason` | blocked("A") → paused reason 없음 → `stop_reason == "A"` |
| `test_leaving_stopped_clears_reason_and_logs` | blocked("A") → doing → `stop_reason == ""`, `stopped_at is None`, ChangeLog `stop_reason` 행 `old_value="A"`, `new_value=""`, note `"상태 변경으로 해제"` |
| `test_done_from_blocked_clears_stop_reason` | blocked("A") → done → `stop_reason == ""`, `completed_at` not None |
| `test_update_stop_reason_rules` | paused task에 `update_task({"stop_reason": "B"})` → 저장, ChangeLog `stop_reason` 행. todo task에 `{"stop_reason": "x"}` → key `stop_reason`. blocked task에 `{"stop_reason": ""}` → key `stop_reason` |
| `test_optimistic_lock_conflict` | `update_task(task, {"priority": 8}, expected_version=1)` 성공(version 2). 다시 `expected_version=1`로 `{"priority": 9}` → `ConflictError`, `exc.latest.version == 2`, `exc.latest.priority == 8` (A13) |
| `test_update_text_does_not_bump_version` | `update_text(task, "notes", "메모")` → `notes == "메모"`, `version == 1`, ChangeLog 수 불변. `update_task(task, {"title": "새 제목", "description": "d"}, expected_version=999)` → 성공(텍스트만이라 version 검사 없음), `version == 1` |
| `test_update_text_title_required` | `update_text(task, "title", "  ")` → key `title`. `update_text(task, "status", "x")` → key `status` |
| `test_update_logs_tracked_fields_only` | `update_task`로 `next_action`, `priority`, `due_date` 동시에 변경 → ChangeLog에 `priority`, `due_date` 행은 있고 `next_action` 행은 없음 |
| `test_move_to_other_team_project_rejected` | 다른 팀 프로젝트로 `project` 변경 → `ServiceError` key `project` |
| `test_extend_due_rules` | 기한 오늘+3인 task: `extend_due(task, 오늘+2, "x")` → key `due_date`. `extend_due(task, 오늘+5, "")` → key `reason`. `extend_due(task, 오늘+5, "회의")` → `due_date == 오늘+5`, `version == 2`, ChangeLog `due_date` 행 note `"연장: 회의"`, `notes`는 그대로 |
| `test_extend_sets_due_when_none` | 기한 없음(사유 "미정") task에 `extend_due(task, 오늘+1, "일정 확정")` → `due_date` 설정, `no_due_reason == ""`, note가 `"목표일 지정: "`로 시작 |
| `test_extend_closed_rejected` | done task → key `due_date` |
| `test_idempotent_create` | 같은 `idempotency_key`로 `create_task` 두 번 → 같은 pk, `Task.objects.count() == 1` |
| `test_checklist_replace_and_done_does_not_complete_task` | `replace_checklist(task, [{"text":"a","is_done":True},{"text":"b","is_done":True}])` → 2건, `task.status`는 여전히 `todo`, `task.version` 불변 (B03) |
| `test_checklist_add_toggle_move_delete` | add 3개 → toggle 첫째 → move 셋째 up → 순서가 `[a,c,b]` → delete → 2개 |
| `test_today_add_does_not_touch_task` | `today_add(member, task)` 전후 `status, due_date, priority, version` 동일, ChangeLog 수 동일 (B01) |
| `test_today_is_private_and_not_carried` | `today_set_auto_pull(member, 0)` 후 `today_add(member, task)`. `today_view(admin)["items"] == []`. `today_view(member, day=내일)["items"] == []` (직접 담은 항목은 날짜별) (B02) |
| `test_today_auto_pull_and_exclude` | member(기본 5일)의 task 3개: 기한 오늘+3, 오늘+10, 없음(사유). `today_view(member)`: `items` 1개(오늘+3), `items[0].auto_pulled is True`, `counts["auto_pulled"] == 1`. `today_exclude(member, 그 task)` → `items == []`, `counts["excluded"] == 1`. `today_restore_excluded(member)` → 다시 1개. `today_add(member, 오늘+10 task)` → `items` 2개, 순서 `[오늘+10(직접), 오늘+3(자동)]` |
| `test_today_flag` | 위 상황에서 `today_flag(오늘+3, today_membership(member)) == "auto"`, 직접 담은 것은 `"manual"`, 기한 없음은 `""`. admin 기준 `today_membership(admin)`으로는 member의 task가 `""` |
| `test_today_settings` | `today_set_auto_pull(member, 4)` → `ServiceError` key `auto_pull_days`. `today_set_auto_pull(member, 0)` → `today_view(member)["counts"]["auto_pulled"] == 0` |
| `test_today_move_and_reorder` | 두 task를 직접 담기 → `today_move(second, "up")` → `items` 순서 뒤집힘 |
| `test_today_focus_is_first_open_and_closed_last` | 직접 담은 task를 done으로 전이, 자동 담긴 task 하나 → `items`는 `[자동(open), 직접(done)]`, `focus`가 자동 담긴 task |
| `test_me_view_groups_by_due` | member의 task 5개: 기한 어제·오늘·이번 주 일요일·다음 주·None(사유) → `me_view(member)`의 그룹 제목이 `["기한 초과","오늘 마감","이번 주 마감","그 이후","기한 미정"]`이고 각 `count == 1`. (오늘이 일요일이면 "이번 주 마감" 케이스는 `today`와 겹치므로 그 경우 그 그룹 검증은 건너뛴다.) 기한별 그룹의 `projects[0]["project"] == project`, `total`·`done` 키 존재 |
| `test_me_view_filters` | 같은 데이터에서 `due="overdue"` → 그룹 1개 count 1. `priority="high"` → 결과 0(기본 5). `status="blocked"` → 0. `group="project"` → 그룹 1개(프로젝트 이름), `flat` True. `status="done_today"` → `completion` True, 제목 "오늘 완료" |
| `test_me_view_member_scope` | `me_view(admin, member=0)` → `read_only` True, hint에 `"보기 전용"`, member의 task 포함. `me_view(admin, member=member)` → 제목 `"팀원의 태스크"`. `me_view(admin)` → 제목 `"내 태스크"`, count 0 |
| `test_search_by_number_title_project` | `search(member, "TASK-1")`, `("메뉴")`, `("학식")` 모두 task 포함. `include_closed=False`면 done task 제외 |
| `test_link_exactly_one_target` | `add_link(task=None, project=None)` → `ServiceError`. `Link.objects.create(project=p, task=t, ...)` → `IntegrityError` |
| `test_no_due_reason_truncated_to_column_length` | 250자 `no_due_reason`으로 생성·수정 → 둘 다 200자. (자르지 않으면 Postgres에서 `DataError` → 500) |
| `test_today_view_is_scoped_to_team_membership` | 담당 태스크가 오늘 목록에 보이는 상태에서 `Membership`을 지우면 `items == []`, `focus is None`, `counts`의 `my_open`·`due_today`·`done_7d` 모두 0 (A01) |
| `test_today_view_manual_item_also_scoped` | `today_set_auto_pull(member, 0)` 후 `today_add` → 보임. `Membership` 삭제 → `items == []`, `focus is None`, `today_membership()["manual"] == set()`. (auto 분기만 막으면 직접 담은 항목이 새어 나간다) |

---

## 7.5 `core/reports/tests.py`

| 테스트 | 검증 |
|---|---|
| `test_weekly_counts_completed_once_per_task` | 지난주로 시각을 맞춘 ChangeLog가 필요하므로: task를 done→재개→done 하고, 생성된 status ChangeLog들의 `created_at`을 `ChangeLog.objects.filter(...).update(created_at=지난주 수요일 12:00 KST)`로 옮긴다. `weekly(team, last_week_start())` → `counts["completed"] == 1`, `counts["reopened"] == 1`, `completed[0]["id"] == task.pk` |
| `test_weekly_rejects_non_monday` | 화요일 날짜 → `ValueError` |
| `test_weekly_shape` | 결과 dict에 키 `team, period_start, period_end, completed, reopened, due_this_week, overdue, blocked, by_project, counts, members` 11개 전부 존재. `counts` 키 8개. `by_project[0]["project"]`에 `status` 키 |
| `test_team_status_counts` | task 4개: 기한 어제(초과), 오늘(이번 주), None(미정), blocked(사유) → `counts["open"]==4`, `overdue==1`, `no_due==1`, `blocked==1`, `due_this_week>=1`. `by_project[0]`에 `owners`(길이 1)·`status` 키, `by_assignee[0]["blocked"] == 1` |

---

## 7.6 `core/api/tests.py`

| 테스트 | 검증 |
|---|---|
| `test_me` | `GET /api/me` → 200, `teams[0]["role"] == "member"`, `auto_pull_days == 5` |
| `test_unauthenticated_401` | 헤더 없이 `GET /api/me` → 401 |
| `test_revoked_token_401` | 토큰 발급 → `revoke()` → `GET /api/me` 401 (A14) |
| `test_read_token_cannot_write` | read 토큰으로 `POST /api/tasks/{id}/transition` → 403. `GET /api/tasks/{id}` → 200 |
| `test_read_token_can_report_integration_status` | read 토큰으로 `POST /api/integrations/discord/status {"ok": true, "detail": {}}` → 204, `IntegrationStatus` 1건 |
| `test_list_tasks_filters_and_paging` | task 3개 생성 → `GET /api/tasks?team=&status=todo&limit=2&offset=0` → `total==3`, `len(items)==2`. `status=bogus` → 400. `status=blocked` → `total==0` |
| `test_create_task_defaults_and_idempotency` | `POST /api/tasks {"project_id","title","due_date"}` 헤더 `Idempotency-Key: k1` 두 번 → 둘 다 201, 같은 `id`. `assignee.id == member.id`, `priority == 5` |
| `test_create_task_validation` | `title=""` → 400, `detail`에 `title` 키. `priority=11` → 422 (스키마 검증) |
| `test_patch_conflict_409_with_latest` | PATCH `{"version":1,"priority":8}` → 200. 다시 `{"version":1,"priority":9}` → 409, `latest["priority"]==8`, `latest["version"]==2` (A13) |
| `test_patch_notes_no_version_bump` | PATCH `{"version":99,"notes":"메모"}` → 200, `notes=="메모"`, `version==1` |
| `test_patch_checklist_replaces` | PATCH `{"version":1,"checklist":[{"text":"x"}]}` → `checklist_total==1` |
| `test_transition_done_via_api_matches_web` | `POST /api/tasks/{id}/transition {"status":"doing","version":1}` → `{"status":"done","version":2}` → 200, `completed_at` not null, `stop_reason==""`, history에 `source=="api"` (A05) |
| `test_transition_blocked_via_api` | `{"status":"blocked","version":1}` → 400 `detail.stop_reason`. `{"status":"blocked","reason":"서류","version":1}` → 200 `stop_reason=="서류"` |
| `test_extend_endpoint` | `POST /api/tasks/{id}/extend {"due_date": 오늘+5, "reason": "회의", "version": 1}` → 200 `due_date` 갱신, `version==2`. `due_date`를 오늘+1로 → 400 `detail.due_date` |
| `test_source_mcp_header_recorded` | 헤더 `X-Source: mcp`로 transition → `GET /api/tasks/{id}/history` 마지막 항목 `source=="mcp"` |
| `test_today_endpoints` | task(기한 오늘+3)는 처음부터 `GET /api/today` `items` 1개 `auto_pulled` true. `DELETE /api/today/{id}` → `items` 0, `counts.excluded==1`. `DELETE /api/today/excluded` → 1개. `POST /api/today {"task_id"}` → `auto_pulled` false. `PATCH /api/today/order {"task_ids":[id]}` → 200. `PATCH /api/today/settings {"auto_pull_days": 4}` → 400. `{"auto_pull_days": 0}` → 200, `auto_pull_days==0` |
| `test_project_owners_via_api` | `POST /api/projects {"team_id","name":"챗봇","owner_ids":[member.id, admin.id]}` → 201, `len(owners)==2`. `PATCH {"version":1,"owner_ids":[]}` → `owners==[]`. `owner_ids:[9999]` → 400 |
| `test_weekly_endpoint` | `GET /api/reports/weekly?team={id}` → 200, `period_start`는 지난주 월요일 isoformat. `week_start=화요일` → 400 |
| `test_team_status_endpoint` | `GET /api/teams/{id}/status` → 200, `counts` 키 존재 |
| `test_invite_admin_only` | member 토큰으로 `POST /api/teams/{id}/invites` → 400. admin 토큰 → 201, `url` 이 `/join/`을 포함 |
| `test_bearer_write_passes_csrf` | `Client(enforce_csrf_checks=True)` + Bearer 토큰으로 `POST /api/tasks/{id}/transition` → 200. (세션 인증이 쿠키 없는 요청까지 CSRF로 막지 않는지) |
| `test_session_write_still_needs_csrf` | 같은 클라이언트로 로그인만 하고 CSRF 토큰 없이 같은 요청 → 403 |
| `test_malformed_date_filter_returns_422_not_500` | `GET /api/tasks?due_from=abc` → 422. 올바른 날짜는 200. (`due_from`이 `str`이면 ORM에서 `ValidationError` → 500) |
| `test_null_due_date_sorts_last_on_both_backends` | 기한 있는 것과 없는 것을 만들고 `GET /api/tasks` → 기한 미정이 뒤에 온다. SQLite·Postgres 동일 |

---

## 7.7 `core/web/tests.py`

| 테스트 | 검증 |
|---|---|
| `test_root_redirects` | 비로그인 `/` → `/login`. 로그인 `/` → `/today` |
| `test_today_page_renders` | member 로그인 `GET /today` → 200, 본문에 "오늘 태스크"와 "빠른 추가" |
| `test_quick_add_creates_task_in_today` | HTMX `POST /today/quick {project, title, priority:5, due_date, idem}` → 204 + 헤더 `HX-Redirect: /today`, `TodayItem` 1건(`excluded=False`) |
| `test_status_change_returns_row` | `POST /tasks/{id}/status {status:"doing", version:1}` → 200, 본문에 `id="task-{id}"`, 헤더 `HX-Trigger`에 `task-updated`, task는 doing (A04) |
| `test_status_blocked_without_reason_shows_error` | `POST /tasks/{id}/status {status:"blocked", version:1}` → 200, 본문에 "막힘 사유", task는 여전히 todo |
| `test_status_change_conflict_shows_message` | version=1로 두 번 → 두 번째 응답 본문에 "먼저 수정했습니다" |
| `test_panel_contains_sections` | `GET /tasks/{id}/panel` → 200, 본문에 "변경 이력", `id="checklist"`, "진행 메모", "목표일" |
| `test_text_autosave` | `POST /tasks/{id}/text/notes {value:"메모"}` → 204, 헤더 `HX-Trigger == "saved"`, `notes=="메모"`, `version==1`. `POST /tasks/{id}/text/title {value:""}` → 400 |
| `test_stop_reason_confirm_block` | `POST /tasks/{id}/stop-reason {reason:"서류", version:1, confirm_block:1}` → 200, task `blocked`, 본문에 "서류". `HX-Trigger`에 `task-changed` |
| `test_extend_from_panel` | `POST /tasks/{id}/extend {due_date: 오늘+5, reason:"회의", version:1}` → 200, 본문에 새 날짜의 "월" 표기, task `due_date` 갱신 |
| `test_project_dialog_and_create` | HTMX `GET /projects/new?team={id}` → 200, 본문에 `<form`과 "프로젝트 만들기". HTMX `POST /projects/new {team, name:"챗봇", status:"active", owners:[admin.id]}` → 204, `HX-Redirect`가 `/projects/`를 포함. 이름 없이 → 200, 본문에 "이름을 입력하세요" |
| `test_project_inline_task_create` | HTMX `POST /projects/{id}/tasks {title, assignee, priority:5, due_date, idem}` → 204, `HX-Redirect`에 `#task-` 포함, task 생성·담당자 지정 |
| `test_me_team_view_read_only` | member 로그인 `GET /me?member=0` → 200, 본문에 "보기 전용"과 `disabled` |
| `test_team_page_renders` | `GET /teams/{id}` → 200, 본문에 "미완료", 프로젝트 이름, "새 프로젝트" |
| `test_signup_then_no_team_message` | `POST /signup` → 302 `/today`, 이후 `/today` 본문에 "초대 링크" |
| `test_ops_requires_staff` | member `/ops` → 302(로그인 페이지) 또는 403. superuser → 200 |
| `test_export_json_has_no_password` | superuser `/ops/export.json` → 200, 본문에 `"password"` 없음 |
| `test_healthz` | `GET /healthz` → 200 `{"ok": true}` |
| `test_token_shown_once` | `POST /settings/tokens {name, scope}` → 302 → `GET` 본문에 `pm_` 포함 → 다시 `GET` 하면 `pm_` 없음 |
| `test_schedule_card_is_scoped_to_team_membership` | `/today?schedule=1&cal=month`에 태스크 제목이 보이는 상태에서 `Membership`을 지우면 사라진다 |
| `test_non_numeric_ids_are_404_not_500` | `GET /projects/new?team=abc` → 404. `POST /projects/new {team: "abc"}` → 404. (`filter(pk="abc")`는 `ValueError` → 500) |
| `test_weird_digit_query_params_do_not_crash` | `/search?q=²`, `/me?member=²`, `/me?project=²` 모두 200. (`isdigit()`은 `²`에 True지만 `int()`는 실패한다) |
| `test_duplicate_discord_id_shows_field_error` | 남이 쓰는 `discord_user_id`를 저장하면 200 + 필드 오류 "이미 쓰는". 값은 바뀌지 않는다 (`IntegrityError` → 500 방지) |
| `test_long_idem_key_does_not_crash` | `POST /today/quick`에 `idem="z"*300` → 200 또는 204. (`IdempotencyKey.key`는 varchar(100)) |
| `test_far_future_schedule_day_does_not_crash` | `/today?schedule=1&cal=month&day=`에 `9999-12-01`·`9999-12-31`·`0001-01-01` → 모두 200. (`week_days()`의 `OverflowError`) |
| `test_admin_task_and_project_are_read_only` | staff로 admin 목록·상세는 200, `add/`·`delete/`는 403, `change/`에 POST는 403이고 값이 안 바뀐다 (GUIDE-00 §3) |
| `test_secret_filter_redacts_tokens_and_webhooks` | `SecretFilter`가 `pm_` 토큰·`Bearer …`·`/u/<token>/`·Discord Webhook URL을 `[redacted]`로 바꾼다. `record.args`를 쓰는 형식도 포함 |

---

## 7.8 실행

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

전부 통과. skip 0. **Postgres에서도 반드시 돌린다** (GUIDE-04의 compose로 db만 띄우고).
varchar 길이 초과와 NULL 정렬은 SQLite에서 드러나지 않으므로 이 실행이 없으면 검증이 끝나지 않는다:

```bash
DATABASE_URL=postgres://pm:pm@localhost:5432/pm uv run pytest -q
```

커밋: `step 7: tests`

---

## 7.9 core 완료 체크리스트

- [x] Step 0~7 검증 전부 통과
- [x] `uv run pytest` SQLite·Postgres 모두 통과 (각 122개, skip 0)
- [x] `ruff check`, `ruff format --check` 오류 0
- [x] `/api/docs`에 5.7 표의 엔드포인트가 전부 보인다 (OpenAPI 경로 20개 확인)
- [x] 01-4 §6.10의 수동 확인 완료 (20항목, 브라우저)
- [x] 목업과 나란히 놓고 다섯 화면 대조 완료. 상세 패널·인라인 폼 문구는 목업과 일치. 차이 9건은 지시서·README가 다르게 지정한 것이거나 목업에만 있는 것이라 [IMPL-REPORT](IMPL-REPORT.md)의 '목업 대조' 절에 기록했다
- [x] 로그에 `pm_` 토큰 원문이 찍히지 않는다 (`SecretFilter` 단위 테스트 + 실제 로깅 설정으로 확인)
- [x] 명세 검수 A01~A14·A18, B01~B05 대응 테스트 확인 (IMPL-REPORT '검수 시나리오 매핑' 표)
- [x] 완료 보고서 작성 ([IMPL-REPORT.md](IMPL-REPORT.md))

다음: [GUIDE-02-discord.md](GUIDE-02-discord.md)
