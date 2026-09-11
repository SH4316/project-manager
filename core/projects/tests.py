import json
from datetime import timedelta

import pytest

from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from orgs.services import create_org
from projects.services import (
    archive_project,
    create_dependency,
    create_milestone,
    create_project,
    fetch_spec,
    parse_spec,
    project_stats,
    restore_project,
    roadmap,
    set_api_spec,
    spec_view,
    update_project,
)
from reports.services import org_status
from tasks.models import ChangeLog
from tasks.services import create_task, transition

pytestmark = pytest.mark.django_db


def test_project_without_owner_allowed(org, admin):
    p = create_project(org=org, name="기타", actor=admin)
    assert p.owners.count() == 0
    names = [row["name"] for row in org_status(org)["projects_without_owner"]]
    assert "기타" in names


def test_owner_must_be_member(org, admin, outsider):
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name="외부", actor=admin, owners=[outsider])
    assert "owners" in e.value.errors


def test_owners_many_and_logged(org, admin, member):
    p = create_project(org=org, name="여럿", actor=admin, owners=[admin, member])
    assert p.owners.count() == 2
    p = update_project(p, {"owners": [member]}, actor=admin, expected_version=1)
    assert [u.pk for u in p.owners.all()] == [member.pk]
    assert (
        ChangeLog.objects.filter(target_type="project", target_id=p.pk, field="owners").count() == 1
    )
    assert p.version == 2


def test_duplicate_name_in_org_rejected(org, admin, project):
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name=project.name, actor=admin)
    assert "name" in e.value.errors


def test_invalid_status_rejected(org, admin):
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name="상태오류", actor=admin, status="closed")
    assert "status" in e.value.errors


def test_archive_blocked_by_open_tasks(project, admin, task):
    with pytest.raises(ServiceError) as e:
        archive_project(project, actor=admin)
    assert task.number in e.value.errors["tasks"]


def test_archive_and_restore(project, admin, member, task):
    transition(task, "done", actor=member, source="web", expected_version=task.version)
    p = archive_project(project, actor=admin)
    assert p.is_archived
    assert (
        ChangeLog.objects.filter(target_type="project", target_id=p.pk, field="is_archived").count()
        == 1
    )
    p = restore_project(p, actor=admin)
    assert not p.is_archived


def test_update_project_conflict(project, admin):
    update_project(project, {"purpose": "a"}, actor=admin, expected_version=1)
    with pytest.raises(ConflictError):
        update_project(project, {"purpose": "b"}, actor=admin, expected_version=1)


def test_member_cannot_archive(project, member):
    with pytest.raises(ServiceError):
        archive_project(project, actor=member)


def test_project_stats_total_excludes_cancelled(project, member):
    due = today_kst() + timedelta(days=1)
    t1 = create_task(project=project, title="a", actor=member, source="web", due_date=due)
    create_task(project=project, title="b", actor=member, source="web", due_date=due)
    t3 = create_task(project=project, title="c", actor=member, source="web", due_date=due)
    transition(t1, "done", actor=member, source="web", expected_version=t1.version)
    transition(t3, "cancelled", actor=member, source="web", expected_version=t3.version)
    st = project_stats(project)
    assert st["total"] == 2
    assert st["done"] == 1
    assert st["open"] == 1


def test_project_name_and_purpose_truncated_to_column_length(org, admin):
    """name varchar(100) / purpose varchar(200). 자르지 않으면 Postgres에서 DataError."""
    p = create_project(org=org, name="N" * 150, purpose="P" * 300, actor=admin)
    assert len(p.name) == 100
    assert len(p.purpose) == 200
    p = update_project(
        p, {"name": "M" * 150, "purpose": "Q" * 300}, actor=admin, expected_version=p.version
    )
    assert len(p.name) == 100
    assert len(p.purpose) == 200


def test_duplicate_check_uses_truncated_name(org, admin):
    """중복 검사와 저장이 같은 값을 써야 한다. 앞 100자가 같은 두 이름이 unique 제약을 때리면 500이 된다."""
    create_project(org=org, name="B" * 100, actor=admin)
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name="B" * 150, actor=admin)
    assert "name" in e.value.errors


def test_removed_member_does_not_freeze_their_projects(org, admin, member, outsider):
    """관리자로 지정된 멤버를 조직에서 제거해도 그 프로젝트의 이름·상태는 고칠 수 있어야 한다."""
    from orgs.models import OrgMembership
    from orgs.services import remove_member

    p = create_project(org=org, name="백엔드", actor=admin, owners=[admin, member])
    remove_member(OrgMembership.objects.get(org=org, user=member), admin)

    p = update_project(p, {"status": "active"}, actor=admin, expected_version=p.version)
    assert p.status == "active"
    assert {u.pk for u in p.owners.all()} == {admin.pk, member.pk}  # 명단은 그대로

    with pytest.raises(ServiceError):  # 새로 넣는 사람은 여전히 조직의 활성 멤버여야 한다
        update_project(p, {"owners": [admin, outsider]}, actor=admin, expected_version=p.version)
    p = update_project(p, {"owners": [admin]}, actor=admin, expected_version=p.version)
    assert [u.pk for u in p.owners.all()] == [admin.pk]


# ---------- 로드맵: 마일스톤 · 프로젝트 의존성 ----------


def test_milestone_validation(project, admin):
    with pytest.raises(ServiceError) as e:
        create_milestone(project=project, name="", target_date=None, actor=admin)
    assert "name" in e.value.errors
    assert "target_date" in e.value.errors

    with pytest.raises(ServiceError) as e:
        create_milestone(
            project=project,
            name="alpha",
            target_date=today_kst(),
            start_date=today_kst() + timedelta(days=1),
            actor=admin,
        )
    assert "start_date" in e.value.errors


def test_roadmap_bar_clipping(project, admin):
    start = today_kst().replace(day=1)
    create_milestone(
        project=project,
        name="걸침",
        start_date=start - timedelta(days=10),
        target_date=start + timedelta(days=5),
        actor=admin,
    )
    data = roadmap(project.org, today=today_kst())
    row = data["rows"][0]
    assert row["left"] == 0
    assert 0 <= row["left"] + row["width"] <= 100


def test_roadmap_hides_out_of_window(project, admin):
    start = today_kst().replace(day=1)
    create_milestone(
        project=project, name="지난달", target_date=start - timedelta(days=1), actor=admin
    )
    data = roadmap(project.org, today=today_kst())
    assert data["hidden"] == 1
    assert data["rows"] == []


def test_roadmap_progress_from_project_stats(project, admin, member):
    t1 = create_task(project=project, title="a", actor=member, source="web", due_date=today_kst())
    t2 = create_task(project=project, title="b", actor=member, source="web", due_date=today_kst())
    transition(t1, "done", actor=member, source="web", expected_version=t1.version)
    create_milestone(
        project=project, name="진행", target_date=today_kst() + timedelta(days=5), actor=admin
    )
    data = roadmap(project.org, today=today_kst())
    st = project_stats(project)
    assert data["rows"][0]["pct"] == round(st["done"] / st["total"] * 100)
    assert t2.status == "todo"  # 완료가 아닌 태스크도 total에는 잡힌다


def test_dependency_same_org_and_not_self(org, admin, project):
    other_org = create_org("다른조직", "", admin)
    other_project = create_project(org=other_org, name="다른", actor=admin)
    with pytest.raises(ServiceError) as e:
        create_dependency(from_project=project, to_project=other_project, actor=admin)
    assert "to_project" in e.value.errors

    with pytest.raises(ServiceError) as e:
        create_dependency(from_project=project, to_project=project, actor=admin)
    assert "to_project" in e.value.errors


def test_dependency_duplicate_rejected(org, admin, project):
    p2 = create_project(org=org, name="두번째", actor=admin)
    create_dependency(from_project=project, to_project=p2, actor=admin)
    with pytest.raises(ServiceError) as e:
        create_dependency(from_project=project, to_project=p2, actor=admin)
    assert "to_project" in e.value.errors


# ---- V2-06: API 문서 ----

SAMPLE_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "학식 API", "version": "1.0.0", "description": "설명"},
    "servers": [{"url": "https://api.example.com"}],
    "tags": [{"name": "tasks", "description": "태스크"}],
    "paths": {
        "/tasks": {
            "get": {
                "tags": ["tasks"],
                "summary": "목록",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 50},
                    }
                ],
                "responses": {"200": {"description": "ok"}},
            },
            "post": {
                "tags": ["tasks"],
                "summary": "생성",
                "security": [{"bearer": []}],
                "requestBody": {"content": {"application/json": {"example": {"title": "a"}}}},
                "responses": {"201": {"description": "created"}, "400": {"description": "bad"}},
            },
        }
    },
}


def test_spec_rejects_without_paths():
    with pytest.raises(ServiceError) as e:
        parse_spec(json.dumps({"info": {}}).encode(), source="x")
    assert "spec" in e.value.errors


def test_spec_rejects_non_json():
    with pytest.raises(ServiceError) as e:
        parse_spec(b"not json", source="x")
    assert "spec" in e.value.errors


def test_spec_rejects_bad_scheme():
    with pytest.raises(ServiceError) as e:
        fetch_spec("file:///etc/passwd")
    assert "spec" in e.value.errors
    with pytest.raises(ServiceError):
        fetch_spec("ftp://example.com/openapi.json")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/openapi.json",  # 이 서버 자신
        "http://localhost:8080/",
        "http://169.254.169.254/latest/meta-data/",  # 클라우드 메타데이터
        "http://10.0.0.5/openapi.json",
        "http://192.168.1.1/openapi.json",
        "http://[::1]:8000/openapi.json",
    ],
)
def test_spec_rejects_internal_addresses(url):
    """서버가 대신 받아 주는 요청이라 사내 주소로 가면 안 된다."""
    with pytest.raises(ServiceError) as e:
        fetch_spec(url)
    assert "spec" in e.value.errors


def test_spec_rejects_redirect_to_internal(monkeypatch):
    """공개 주소가 사내로 되돌리는 것도 막는다."""
    from projects.services import _SafeRedirect

    handler = _SafeRedirect()
    with pytest.raises(ServiceError):
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1:8000/x")


def test_spec_rejects_oversize():
    with pytest.raises(ServiceError) as e:
        parse_spec(b"x" * (5 * 1024 * 1024 + 1), source="x")
    assert "spec" in e.value.errors


def test_spec_saved_and_replaced(project, admin):
    obj = set_api_spec(project, SAMPLE_SPEC, source_url="a.json", actor=admin)
    assert obj.project_id == project.pk
    obj2 = set_api_spec(project, SAMPLE_SPEC, source_url="b.json", actor=admin)
    assert obj2.pk == obj.pk
    from projects.models import ApiSpec

    assert ApiSpec.objects.filter(project=project).count() == 1
    assert obj2.source_url == "b.json"


def test_spec_view_groups_by_tag():
    v = spec_view(SAMPLE_SPEC)
    assert v["title"] == "학식 API"
    assert v["version"] == "v1.0.0"
    assert v["count"] == 2
    assert [g["tag"] for g in v["groups"]] == ["tasks"]
    ops = {op["method"]: op for op in v["groups"][0]["ops"]}
    assert ops["POST"]["auth"] is True
    assert ops["POST"]["body"]["example"]
    assert ops["GET"]["params"][0]["name"] == "limit"


def test_spec_view_search_filters():
    v = spec_view(SAMPLE_SPEC, q="생성")
    assert v["count"] == 1
    assert v["groups"][0]["ops"][0]["method"] == "POST"
    v2 = spec_view(SAMPLE_SPEC, q="없는말")
    assert v2["count"] == 0


def test_spec_view_method_colors():
    v = spec_view(SAMPLE_SPEC)
    ops = {op["method"]: op for op in v["groups"][0]["ops"]}
    assert ops["GET"]["color"] == "#1F6F82"
    assert ops["POST"]["color"] == "#12793F"


def test_spec_view_handles_missing_fields():
    v = spec_view({"paths": {"/x": {"get": {}}}})
    assert v["title"] == "제목 없는 API"
    assert v["version"] == "버전 없음"
    assert v["server"] == "서버 정보 없음"
    assert v["count"] == 1
