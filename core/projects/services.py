from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from teams.services import is_member, require_admin

from .models import Project

EDITABLE = {"name", "purpose", "owners", "status"}


def _log(project, field, old, new, actor, source, token=None, note=""):
    from tasks.models import ChangeLog

    ChangeLog.objects.create(
        target_type="project",
        target_id=project.pk,
        field=field,
        old_value=_s(old),
        new_value=_s(new),
        note=note,
        actor=actor,
        source=source,
        token=token,
    )


def _s(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "pk"):
        return str(v.pk)
    return str(v)


def _ids(users) -> str:
    """관리자 목록을 이력에 남길 때 쓰는 문자열: '1,4'."""
    return ",".join(str(pk) for pk in sorted(u.pk for u in users))


def _validate(team, name, owners, status):
    errors = {}
    if not name or not name.strip():
        errors["name"] = "프로젝트 이름을 입력하세요."
    for u in owners:
        if not u.is_active or not is_member(u, team):
            errors["owners"] = "관리자는 이 팀의 활성 멤버여야 합니다."
            break
    if status not in dict(Project.STATUSES):
        errors["status"] = "알 수 없는 상태입니다."
    if errors:
        raise ServiceError(errors)


@transaction.atomic
def create_project(
    *, team, name, actor, source="web", token=None, purpose="", owners=(), status="preparing"
):
    if not is_member(actor, team):
        raise ServiceError({"team": "이 팀의 멤버가 아닙니다."})
    owners = list(owners)
    _validate(team, name, owners, status)
    if Project.objects.filter(team=team, name=name.strip()).exists():
        raise ServiceError({"name": "같은 이름의 프로젝트가 이미 있습니다."})
    project = Project.objects.create(
        team=team,
        name=name.strip()[:100],
        purpose=purpose.strip()[:200],
        status=status,
        created_by=actor,
    )
    project.owners.set(owners)
    _log(project, "created", "", project.name, actor, source, token)
    return project


@transaction.atomic
def update_project(
    project, changes: dict, *, actor, source="web", token=None, expected_version: int
):
    if not is_member(actor, project.team):
        raise ServiceError({"team": "이 팀의 멤버가 아닙니다."})
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ServiceError({k: "수정할 수 없는 항목입니다." for k in sorted(unknown)})
    old_owners = list(project.owners.all())
    new_owners = list(changes.get("owners", old_owners))
    new = {f: changes.get(f, getattr(project, f)) for f in ("name", "purpose", "status")}
    _validate(project.team, new["name"], new_owners, new["status"])
    new["name"] = new["name"].strip()[:100]
    new["purpose"] = (new["purpose"] or "").strip()[:200]
    if (
        new["name"] != project.name
        and Project.objects.filter(team=project.team, name=new["name"]).exists()
    ):
        raise ServiceError({"name": "같은 이름의 프로젝트가 이미 있습니다."})
    old = {f: getattr(project, f) for f in ("name", "purpose", "status")}
    fields = {f: v for f, v in new.items() if v != old[f]}
    owners_changed = {u.pk for u in new_owners} != {u.pk for u in old_owners}
    if not fields and not owners_changed:
        return project
    updated = Project.objects.filter(pk=project.pk, version=expected_version).update(
        version=expected_version + 1, updated_at=timezone.now(), **fields
    )
    if updated != 1:
        project.refresh_from_db()
        raise ConflictError(project)
    if owners_changed:
        project.owners.set(new_owners)
        _log(project, "owners", _ids(old_owners), _ids(new_owners), actor, source, token)
    project.refresh_from_db()
    if "status" in fields:
        _log(project, "status", old["status"], fields["status"], actor, source, token)
    return project


@transaction.atomic
def archive_project(project, *, actor, source="web", token=None):
    """미완료 태스크가 있으면 ServiceError. errors['tasks']에 'TASK-1, TASK-2' 형식."""
    from tasks.models import Task

    require_admin(actor, project.team)
    open_tasks = list(Task.objects.filter(project=project, status__in=Task.OPEN).order_by("id"))
    if open_tasks:
        raise ServiceError({"tasks": ", ".join(t.number for t in open_tasks)})
    if project.is_archived:
        return project
    Project.objects.filter(pk=project.pk).update(
        is_archived=True, archived_at=timezone.now(), version=project.version + 1
    )
    project.refresh_from_db()
    _log(project, "is_archived", False, True, actor, source, token)
    return project


@transaction.atomic
def restore_project(project, *, actor, source="web", token=None):
    require_admin(actor, project.team)
    if not project.is_archived:
        return project
    Project.objects.filter(pk=project.pk).update(
        is_archived=False, archived_at=None, version=project.version + 1
    )
    project.refresh_from_db()
    _log(project, "is_archived", True, False, actor, source, token)
    return project


def project_stats(project) -> dict:
    """{'total','open','overdue','review','blocked','done'}. total은 취소를 뺀 수."""
    from tasks.models import Task

    today = today_kst()
    return Task.objects.filter(project=project).aggregate(
        total=Count("id", filter=~Q(status="cancelled")),
        open=Count("id", filter=Q(status__in=Task.OPEN)),
        overdue=Count("id", filter=Q(status__in=Task.OPEN, due_date__lt=today)),
        review=Count("id", filter=Q(status="review")),
        blocked=Count("id", filter=Q(status="blocked")),
        done=Count("id", filter=Q(status="done")),
    )
