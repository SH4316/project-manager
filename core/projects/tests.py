from datetime import timedelta

import pytest

from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from projects.services import (
    archive_project,
    create_project,
    project_stats,
    restore_project,
    update_project,
)
from reports.services import team_status
from tasks.models import ChangeLog
from tasks.services import create_task, transition

pytestmark = pytest.mark.django_db


def test_project_without_owner_allowed(team, admin):
    p = create_project(team=team, name="기타", actor=admin)
    assert p.owners.count() == 0
    names = [row["name"] for row in team_status(team)["projects_without_owner"]]
    assert "기타" in names


def test_owner_must_be_member(team, admin, outsider):
    with pytest.raises(ServiceError) as e:
        create_project(team=team, name="외부", actor=admin, owners=[outsider])
    assert "owners" in e.value.errors


def test_owners_many_and_logged(team, admin, member):
    p = create_project(team=team, name="여럿", actor=admin, owners=[admin, member])
    assert p.owners.count() == 2
    p = update_project(p, {"owners": [member]}, actor=admin, expected_version=1)
    assert [u.pk for u in p.owners.all()] == [member.pk]
    assert (
        ChangeLog.objects.filter(target_type="project", target_id=p.pk, field="owners").count() == 1
    )
    assert p.version == 2


def test_duplicate_name_in_team_rejected(team, admin, project):
    with pytest.raises(ServiceError) as e:
        create_project(team=team, name=project.name, actor=admin)
    assert "name" in e.value.errors


def test_invalid_status_rejected(team, admin):
    with pytest.raises(ServiceError) as e:
        create_project(team=team, name="상태오류", actor=admin, status="closed")
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


def test_project_name_and_purpose_truncated_to_column_length(team, admin):
    """name varchar(100) / purpose varchar(200). 자르지 않으면 Postgres에서 DataError."""
    p = create_project(team=team, name="N" * 150, purpose="P" * 300, actor=admin)
    assert len(p.name) == 100
    assert len(p.purpose) == 200
    p = update_project(
        p, {"name": "M" * 150, "purpose": "Q" * 300}, actor=admin, expected_version=p.version
    )
    assert len(p.name) == 100
    assert len(p.purpose) == 200


def test_duplicate_check_uses_truncated_name(team, admin):
    """중복 검사와 저장이 같은 값을 써야 한다. 앞 100자가 같은 두 이름이 unique 제약을 때리면 500이 된다."""
    create_project(team=team, name="B" * 100, actor=admin)
    with pytest.raises(ServiceError) as e:
        create_project(team=team, name="B" * 150, actor=admin)
    assert "name" in e.value.errors
