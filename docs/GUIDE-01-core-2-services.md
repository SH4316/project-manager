# 구현 지시서 01-2: core — 서비스 계층 (Step 3, 4)

이전: [01-1](GUIDE-01-core-1-setup-models.md). 이 문서의 코드는 **그대로** 옮긴다. 업무 규칙은 전부 여기 있다. 뷰와 API는 이 함수들만 부른다.

개정 2026-09-10: 상태 7개·멈춤 사유, 중요도 1~10, `update_text`(version 없는 자동 저장), `extend_due`, 댓글 삭제, 오늘 목록 자동 담기·제외, `me_view`, 프로젝트 관리자 여러 명.

---

## Step 3. services

### 3.1 `core/teams/services.py`

```python
from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import Invite, Membership, Team


def teams_of(user):
    """user가 속한 팀 queryset."""
    return Team.objects.filter(memberships__user=user).distinct()


def is_member(user, team) -> bool:
    return Membership.objects.filter(team=team, user=user).exists()


def is_admin(user, team) -> bool:
    return Membership.objects.filter(team=team, user=user, role="admin").exists()


def require_admin(user, team):
    if not is_admin(user, team):
        raise ServiceError({"team": "팀 관리자만 할 수 있습니다."})


@transaction.atomic
def create_team(name: str, purpose: str, actor) -> Team:
    name = name.strip()
    if not name:
        raise ServiceError({"name": "팀 이름을 입력하세요."})
    team = Team.objects.create(name=name[:100], purpose=purpose.strip()[:200], created_by=actor)
    Membership.objects.create(team=team, user=actor, role="admin")
    return team


def create_invite(team, actor, days: int = 7) -> Invite:
    require_admin(actor, team)
    if not 1 <= days <= 90:
        raise ServiceError({"days": "만료일은 1~90일 사이여야 합니다."})
    expires_at = timezone.now() + timezone.timedelta(days=days)
    return Invite.objects.create(team=team, created_by=actor, expires_at=expires_at)


def revoke_invite(invite, actor):
    require_admin(actor, invite.team)
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])


@transaction.atomic
def join_by_token(user, token: str) -> Team:
    invite = Invite.objects.select_for_update().select_related("team").filter(token=token).first()
    if invite is None or not invite.is_usable:
        raise ServiceError({"token": "초대 링크가 유효하지 않거나 만료되었습니다."})
    _, created = Membership.objects.get_or_create(
        team=invite.team, user=user, defaults={"role": "member"}
    )
    if created:
        invite.use_count += 1
        invite.save(update_fields=["use_count"])
    return invite.team


def change_role(membership, role: str, actor):
    require_admin(actor, membership.team)
    if role not in dict(Membership.ROLES):
        raise ServiceError({"role": "알 수 없는 역할입니다."})
    if membership.role == "admin" and role != "admin" and _admin_count(membership.team) <= 1:
        raise ServiceError({"role": "마지막 관리자의 역할은 바꿀 수 없습니다."})
    membership.role = role
    membership.save(update_fields=["role"])


def remove_member(membership, actor):
    require_admin(actor, membership.team)
    if membership.role == "admin" and _admin_count(membership.team) <= 1:
        raise ServiceError({"member": "마지막 관리자는 제거할 수 없습니다."})
    membership.delete()


def _admin_count(team) -> int:
    return Membership.objects.filter(team=team, role="admin").count()


# ---------- Discord 알림 채널 ----------

WEBHOOK_HELP = "Discord 채널 → 설정 → 연동 → 웹후크에서 만든 주소를 붙여넣으세요."


def webhooks_of(team):
    return DiscordWebhook.objects.filter(team=team).select_related("created_by")


def active_webhook_urls(team) -> list[str]:
    """discord 서비스가 읽어 가는 발송 대상. 순서는 이름순으로 고정한다."""
    return list(webhooks_of(team).filter(is_active=True).values_list("url", flat=True))


def add_webhook(team, name: str, url: str, actor) -> DiscordWebhook:
    require_admin(actor, team)
    name, url = name.strip()[:50], url.strip()
    if not name:
        raise ServiceError({"name": "채널 이름을 입력하세요."})
    if not WEBHOOK_RE.match(url):
        raise ServiceError({"url": "Discord Webhook 주소 형식이 아닙니다."})
    if DiscordWebhook.objects.filter(team=team, url=url).exists():
        raise ServiceError({"url": "이미 등록한 Webhook입니다."})
    return DiscordWebhook.objects.create(team=team, name=name, url=url, created_by=actor)


def set_webhook_active(webhook, active: bool, actor):
    require_admin(actor, webhook.team)
    if webhook.is_active != active:
        webhook.is_active = active
        webhook.save(update_fields=["is_active"])


def delete_webhook(webhook, actor):
    require_admin(actor, webhook.team)
    webhook.delete()


def send_test_message(webhook, actor, send=None) -> tuple[bool, str]:
    """확인용 메시지 1건을 보내고 결과를 기록한다. (성공?, 사유) 를 돌려준다.

    실패 사유에 URL이 섞이지 않도록 예외 원문은 쓰지 않는다(GUIDE-00 §3).
    """
    require_admin(actor, webhook.team)
    if webhook.last_test_at and (timezone.now() - webhook.last_test_at).total_seconds() < 30:
        raise ServiceError({"url": "잠시 후 다시 시도하세요."})
    send = send or post_discord
    try:
        send(webhook.url, f"✅ {webhook.team.name} 알림 연결 확인")
        ok, detail = True, ""
    except urllib.error.HTTPError as e:
        ok, detail = (
            False,
            f"Discord 응답 {e.code}" + (" (삭제된 Webhook)" if e.code == 404 else ""),
        )
    except Exception:  # noqa: BLE001  네트워크·DNS·타임아웃
        ok, detail = False, "Discord에 연결하지 못했습니다."
    DiscordWebhook.objects.filter(pk=webhook.pk).update(
        last_test_at=timezone.now(), last_test_ok=ok, last_test_detail=detail
    )
    return ok, detail


def post_discord(url: str, text: str) -> None:
    """core가 Discord로 직접 보내는 유일한 곳(등록 확인용 1건).

    정기 알림은 discord 서비스의 일이다. 주소는 add_webhook의 WEBHOOK_RE로 이미 검증되어
    discord.com 밖으로는 나가지 않는다.
    """
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()
```

- 웹훅 관리는 전부 `require_admin`을 거친다. 화면(`views/teams.py`)은 팀 관리자가 아니면
  404로 감추고, 실제 차단은 여기서 한다.
- `add_webhook`은 `WEBHOOK_RE`로 주소를 검사한다. 이 검사가 곧 SSRF 방지다
  (검사를 통과한 주소만 `post_discord`가 연다).
- `send_test_message`의 실패 사유에는 예외 원문을 쓰지 않는다. 예외 문구에 주소가 섞여
  화면·로그로 새는 것을 막는다(GUIDE-00 §3).
- 정기 알림은 discord 서비스가 보낸다. core가 Discord로 직접 보내는 곳은
  `post_discord`(등록 확인용 1건) 하나뿐이다.

### 3.2 `core/projects/services.py`

```python
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
        note=note[:200],
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
    # 저장할 값과 같은 값으로 검사해야 한다. 자르기 전 값으로 검사하면
    # 앞 100자가 같은 두 이름이 둘 다 통과해 INSERT에서 unique 제약에 걸린다.
    name = name.strip()[:100]
    if Project.objects.filter(team=team, name=name).exists():
        raise ServiceError({"name": "같은 이름의 프로젝트가 이미 있습니다."})
    project = Project.objects.create(
        team=team, name=name, purpose=purpose.strip()[:200], status=status, created_by=actor
    )
    project.owners.set(owners)
    _log(project, "created", "", project.name, actor, source, token)
    return project


@transaction.atomic
def update_project(project, changes: dict, *, actor, source="web", token=None, expected_version: int):
    if not is_member(actor, project.team):
        raise ServiceError({"team": "이 팀의 멤버가 아닙니다."})
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ServiceError({k: "수정할 수 없는 항목입니다." for k in sorted(unknown)})
    old_owners = list(project.owners.all())
    new_owners = list(changes.get("owners", old_owners))
    new = {f: changes.get(f, getattr(project, f)) for f in ("name", "purpose", "status")}
    # 새로 넣는 관리자만 검사한다. 이미 있던 사람이 팀에서 빠지면 그 프로젝트의
    # 이름·상태조차 못 고치게 되기 때문이다(태스크 담당자와 같은 이유).
    old_ids = {u.pk for u in old_owners}
    _validate(
        project.team, new["name"], [u for u in new_owners if u.pk not in old_ids], new["status"]
    )
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
```

### 3.3 `core/tasks/services.py`

```python
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounts.models import IdempotencyKey, User
from common.dates import kst_day_range, today_kst, week_bounds
from common.errors import ConflictError, ServiceError
from projects.services import project_stats
from teams.services import is_member, teams_of

from .models import ChangeLog, ChecklistItem, Link, Task, TodayItem

# 자동 저장되는 부속 텍스트. version·ChangeLog 없음.
TEXT_FIELDS = ("title", "description", "done_when", "next_action", "notes")
TEXT_MAX = {"title": 200, "done_when": 300, "next_action": 200}
# 낙관적 잠금이 걸리는 팀 데이터
LOCKED_FIELDS = {"assignee", "priority", "due_date", "no_due_reason", "project", "stop_reason"}
EDITABLE = LOCKED_FIELDS | set(TEXT_FIELDS)
TRACKED = ("assignee", "due_date", "project", "priority", "stop_reason")

NO_DUE_FOR_DOING = "목표 기한이 없어서 진행 중으로 바꾸지 못했어요. 기한을 먼저 정해 주세요."

# 내 태스크 화면 필터 값. (코드, 화면 표기)
DUE_FILTERS = [
    ("", "모든 기한"),
    ("overdue", "기한 초과"),
    ("today", "오늘 마감"),
    ("week", "이번 주 남은 마감"),
    ("this_week", "이번 주 전체 마감"),
    ("later", "그 이후"),
    ("none", "기한 미정"),
]
STATUS_FILTERS = (
    [("", "모든 상태")]
    + [(c, label) for c, label in Task.STATUSES if c in Task.OPEN]
    + [("done_today", "오늘 완료"), ("done_7d", "지난 7일 완료")]
)
PRIORITY_FILTERS = [("", "모든 중요도")] + Task.TIER_LABELS
GROUP_OPTIONS = [("due", "기한별"), ("project", "프로젝트별"), ("status", "상태별")]


# ---------- 공통 ----------

def _s(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "pk"):
        return str(v.pk)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _log(task, field, old, new, actor, source, token=None, note=""):
    ChangeLog.objects.create(
        target_type="task", target_id=task.pk, field=field,
        old_value=_s(old), new_value=_s(new), note=note[:200],
        actor=actor, source=source, token=token,
    )


def _require_member(actor, project):
    if not is_member(actor, project.team):
        raise ServiceError({"project": "이 팀의 멤버가 아닙니다."})


def _validate(
    *,
    project,
    assignee,
    status,
    priority,
    due_date,
    no_due_reason,
    stop_reason,
    title,
    check_assignee=True,
):
    """check_assignee=False면 담당자가 팀의 활성 멤버인지 보지 않는다.

    담당자를 바꾸지 않는 수정에는 이 검사를 걸지 않는다. 담당자가 팀에서 빠지거나
    비활성이 되면(팀원 관리 화면의 [제거]) 그 태스크의 중요도·기한조차 못 고치게 되고,
    화면에는 이미 나간 사람 이름이 담긴 오류만 나온다.
    """
    errors = {}
    if not title or not title.strip():
        errors["title"] = "제목을 입력하세요."
    if project.is_archived:
        errors["project"] = "보관된 프로젝트에는 태스크를 둘 수 없습니다."
    if assignee is None:
        errors["assignee"] = "담당자를 지정하세요."
    elif check_assignee and (not assignee.is_active or not is_member(assignee, project.team)):
        errors["assignee"] = "담당자는 이 팀의 활성 멤버여야 합니다."
    if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 10:
        errors["priority"] = "중요도는 1~10 사이의 정수여야 합니다."
    if status == "doing" and due_date is None:
        errors["due_date"] = NO_DUE_FOR_DOING
    elif status in Task.OPEN and due_date is None and not (no_due_reason or "").strip():
        errors["no_due_reason"] = "기한이 없으면 사유를 입력하세요."
    reason = (stop_reason or "").strip()
    if status == "blocked" and not reason:
        errors["stop_reason"] = "막힘 사유를 입력하세요."
    if status not in Task.STOPPED and reason:
        errors["stop_reason"] = "일시정지·막힘 상태에서만 사유를 둘 수 있습니다."
    if errors:
        raise ServiceError(errors)


def _apply(task, expected_version: int, fields: dict):
    """낙관적 잠금 갱신. 버전이 다르면 ConflictError(최신 객체)."""
    updated = Task.objects.filter(pk=task.pk, version=expected_version).update(
        version=expected_version + 1, updated_at=timezone.now(), **fields
    )
    if updated != 1:
        task.refresh_from_db()
        raise ConflictError(task)
    task.refresh_from_db()


def visible_tasks(user):
    """user가 볼 수 있는 태스크 queryset (내 팀 범위)."""
    return Task.objects.filter(project__team__in=teams_of(user)).select_related(
        "project", "project__team", "assignee"
    )


def get_visible_task(user, task_id: int) -> Task | None:
    return visible_tasks(user).filter(pk=task_id).first()


def by_due(t):
    """기한 오름차순, 기한 없음은 뒤로, 같으면 id."""
    return (t.due_date or date.max, t.pk)


# ---------- 생성·수정 ----------

@transaction.atomic
def create_task(
    *, project, title, actor, source, token=None, assignee=None, description="",
    done_when="", next_action="", priority=5, due_date=None, no_due_reason="",
    idempotency_key=None,
) -> Task:
    _require_member(actor, project)
    if idempotency_key:
        idempotency_key = idempotency_key[:100]  # 컬럼은 varchar(100)
        hit = IdempotencyKey.objects.filter(
            user=actor, key=idempotency_key, target_type="task"
        ).first()
        if hit:
            return Task.objects.get(pk=hit.target_id)
    assignee = assignee or actor
    _validate(
        project=project, assignee=assignee, status="todo", priority=priority,
        due_date=due_date, no_due_reason=no_due_reason, stop_reason="", title=title,
    )
    task = Task.objects.create(
        project=project, title=title.strip()[:200], description=description or "",
        done_when=(done_when or "")[:300], next_action=(next_action or "")[:200],
        assignee=assignee, priority=priority, due_date=due_date,
        no_due_reason=(no_due_reason or "").strip()[:200], created_by=actor,
    )
    _log(task, "created", "", task.number, actor, source, token)
    if idempotency_key:
        IdempotencyKey.objects.create(
            user=actor, key=idempotency_key, target_type="task", target_id=task.pk
        )
    return task


def update_text(task, field: str, value: str, *, actor) -> Task:
    """제목·설명·완료 조건·다음 행동·진행 메모 자동 저장. version·ChangeLog를 건드리지 않는다.
    # ponytail: 부속 텍스트는 last-write-wins. 동시 편집 보호가 필요해지면 필드별 갱신 시각 비교로.
    """
    _require_member(actor, task.project)
    if field not in TEXT_FIELDS:
        raise ServiceError({field: "수정할 수 없는 항목입니다."})
    value = value or ""
    if field == "title":
        value = value.strip()
        if not value:
            raise ServiceError({"title": "제목을 입력하세요."})
    if field in TEXT_MAX:
        value = value[:TEXT_MAX[field]]
    Task.objects.filter(pk=task.pk).update(**{field: value}, updated_at=timezone.now())
    task.refresh_from_db()
    return task


@transaction.atomic
def update_task(task, changes: dict, *, actor, source, token=None, expected_version: int) -> Task:
    """팀 데이터 필드는 version 검사 후 갱신·이력 기록. TEXT_FIELDS는 update_text로 보낸다."""
    _require_member(actor, task.project)
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ServiceError({k: "수정할 수 없는 항목입니다." for k in sorted(unknown)})
    for f in TEXT_FIELDS:
        if f in changes:
            update_text(task, f, changes[f], actor=actor)
    changes = {f: v for f, v in changes.items() if f in LOCKED_FIELDS}
    if not changes:
        return task
    new = {f: changes.get(f, getattr(task, f)) for f in LOCKED_FIELDS}
    if "project" in changes:
        _require_member(actor, new["project"])
        if new["project"].team_id != task.project.team_id:
            raise ServiceError({"project": "다른 팀의 프로젝트로 옮길 수 없습니다."})
    new["no_due_reason"] = (new["no_due_reason"] or "").strip()[:200]
    new["stop_reason"] = (new["stop_reason"] or "").strip()[:300]
    _validate(
        project=new["project"], assignee=new["assignee"], status=task.status,
        priority=new["priority"], due_date=new["due_date"], no_due_reason=new["no_due_reason"],
        stop_reason=new["stop_reason"], title=task.title,
        check_assignee="assignee" in changes,
    )
    old = {f: getattr(task, f) for f in LOCKED_FIELDS}
    fields = {f: v for f, v in new.items() if v != old[f]}
    if not fields:
        return task
    _apply(task, expected_version, fields)
    for f in TRACKED:
        if f in fields:
            _log(task, f, old[f], fields[f], actor, source, token)
    return task


@transaction.atomic
def transition(task, new_status: str, *, actor, source, token=None, reason="", expected_version: int) -> Task:
    """상태 변경. 규칙:
    - 미완료 5개 사이는 자유. 미완료 → 완료·취소 가능. 완료·취소 → 시작 전·진행 중으로만 재개.
    - 같은 상태 재요청은 아무것도 바꾸지 않는다 (A06).
    - doing 진입 시 기한 필수. blocked 진입 시 reason 필수. paused는 reason 선택.
    - paused·blocked 밖으로 나가면 stop_reason·stopped_at 초기화.
    - done 진입 시 completed_at=now. 재개·취소 시 completed_at=None.
    - 재개 사유(reason)는 선택. 있으면 이력 note에 남는다.
    """
    _require_member(actor, task.project)
    labels = dict(Task.STATUSES)
    if new_status not in labels:
        raise ServiceError({"status": "알 수 없는 상태입니다."})
    if new_status == task.status:
        return task
    if task.is_closed and new_status not in ("todo", "doing"):
        raise ServiceError({
            "status": f"{labels[task.status]}에서 {labels[new_status]}(으)로 바꿀 수 없습니다. 먼저 시작 전이나 진행 중으로 다시 여세요."
        })
    reason = (reason or "").strip()[:300]
    if new_status == "doing" and task.due_date is None:
        raise ServiceError({"due_date": NO_DUE_FOR_DOING})
    if new_status == "blocked" and not reason:
        raise ServiceError({"stop_reason": "막힘 사유를 입력하세요."})
    fields = {"status": new_status}
    if new_status in Task.STOPPED:
        fields["stop_reason"] = reason or (task.stop_reason if task.is_stopped else "")
        if not task.is_stopped:
            fields["stopped_at"] = timezone.now()
    else:
        fields["stop_reason"] = ""
        fields["stopped_at"] = None
    if new_status == "done":
        fields["completed_at"] = timezone.now()
    elif task.is_closed or new_status == "cancelled":
        fields["completed_at"] = None
    old_status, old_completed, old_reason = task.status, task.completed_at, task.stop_reason
    _apply(task, expected_version, fields)
    _log(task, "status", old_status, new_status, actor, source, token, note=reason)
    if old_status == "done" and old_completed is not None:
        _log(task, "completed_at", old_completed, None, actor, source, token, note="재개")
    if old_reason and not task.stop_reason:
        _log(task, "stop_reason", old_reason, "", actor, source, token, note="상태 변경으로 해제")
    return task


@transaction.atomic
def extend_due(task, new_date: date | None, reason: str, *, actor, source, token=None, expected_version: int) -> Task:
    """목표일 연장. 기한이 없던 태스크는 목표일 정하기. 새 날짜는 현 기한보다 뒤, 사유 필수.
    이력에 'due_date' 행 하나, note='연장: 사유'. 진행 메모는 건드리지 않는다."""
    _require_member(actor, task.project)
    if not task.is_open:
        raise ServiceError({"due_date": "완료·취소된 태스크의 기한은 바꿀 수 없습니다."})
    if new_date is None:
        raise ServiceError({"due_date": "새 목표일을 선택하세요."})
    if task.due_date is not None and new_date <= task.due_date:
        raise ServiceError({"due_date": "현재 목표일보다 뒤의 날짜를 선택하세요."})
    reason = (reason or "").strip()
    if not reason:
        raise ServiceError({"reason": "연장 사유를 입력하세요."})
    old = task.due_date
    _apply(task, expected_version, {"due_date": new_date, "no_due_reason": ""})
    note = f"연장: {reason}" if old else f"목표일 지정: {reason}"
    _log(task, "due_date", old, new_date, actor, source, token, note=note)
    return task


# ---------- 링크 ----------

def add_link(*, actor, title, url, kind="doc", task=None, project=None) -> Link:
    if (task is None) == (project is None):
        raise ServiceError({"target": "태스크 또는 프로젝트 중 하나에만 연결합니다."})
    target_project = project if project is not None else task.project
    _require_member(actor, target_project)
    title, url = (title or "").strip(), (url or "").strip()
    if not title or not url:
        raise ServiceError({"url": "제목과 URL을 입력하세요."})
    if not url.startswith(("http://", "https://")):
        raise ServiceError({"url": "http:// 또는 https:// 로 시작해야 합니다."})
    if kind not in dict(Link.KINDS):
        raise ServiceError({"kind": "알 수 없는 종류입니다."})
    return Link.objects.create(
        task=task, project=project, title=title[:100], url=url[:500], kind=kind, created_by=actor
    )


def delete_link(link, *, actor):
    target_project = link.project or link.task.project
    _require_member(actor, target_project)
    link.delete()


# ---------- 체크리스트 ----------

@transaction.atomic
def replace_checklist(task, items: list[dict], *, actor) -> list[ChecklistItem]:
    """items: [{'text': str, 'is_done': bool}, ...]. 전체 교체."""
    _require_member(actor, task.project)
    cleaned = []
    for i, item in enumerate(items):
        text = (item.get("text") or "").strip()
        if not text:
            raise ServiceError({"checklist": f"{i + 1}번째 항목의 내용이 비어 있습니다."})
        cleaned.append(ChecklistItem(task=task, text=text[:200], is_done=bool(item.get("is_done")), position=i))
    task.checklist.all().delete()
    ChecklistItem.objects.bulk_create(cleaned)
    return list(task.checklist.all())


def checklist_add(task, text: str, *, actor) -> ChecklistItem:
    _require_member(actor, task.project)
    text = (text or "").strip()
    if not text:
        raise ServiceError({"text": "내용을 입력하세요."})
    pos = (task.checklist.aggregate(m=Max("position"))["m"] or 0) + 1
    return ChecklistItem.objects.create(task=task, text=text[:200], position=pos)


def checklist_toggle(item, *, actor) -> ChecklistItem:
    _require_member(actor, item.task.project)
    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])
    return item


def checklist_delete(item, *, actor):
    _require_member(actor, item.task.project)
    item.delete()


def checklist_move(item, direction: str, *, actor):
    """direction: 'up' | 'down'. 이웃과 position을 맞바꾼다."""
    _require_member(actor, item.task.project)
    siblings = list(item.task.checklist.all())
    idx = siblings.index(item)
    j = idx - 1 if direction == "up" else idx + 1
    if 0 <= j < len(siblings):
        siblings[idx], siblings[j] = siblings[j], siblings[idx]
        for pos, s in enumerate(siblings):
            ChecklistItem.objects.filter(pk=s.pk).update(position=pos)


# ---------- 오늘 목록 (개인 계획) ----------
# 오늘 목록 = 직접 담은 것 ∪ (내 미완료 태스크 중 기한 ≤ 오늘+auto_pull_days, '오늘 제외' 아님).
# 어느 조작도 Task의 상태·기한·중요도·version·ChangeLog를 건드리지 않는다.

def _pull_end(user, day: date) -> date | None:
    n = user.auto_pull_days
    return day + timedelta(days=n) if n > 0 else None


def today_items(user, day: date):
    """그 날짜의 오늘 목록 행. 팀 범위를 벗어난 태스크는 제외한다.

    TodayItem은 담은 시점의 기록이라, 그 뒤 팀에서 빠지면 남아 있을 수 있다.
    담기·읽기 두 경로가 같은 범위를 쓰도록 여기 한 곳에서 거른다.
    """
    return TodayItem.objects.filter(user=user, date=day, task__project__team__in=teams_of(user))


def today_membership(user, day: date | None = None) -> dict:
    """행 렌더링용. 키: user_id, manual(set), excluded(set), pull_end."""
    day = day or today_kst()
    rows = today_items(user, day).values_list("task_id", "excluded")
    return {
        "user_id": user.pk,
        "manual": {tid for tid, ex in rows if not ex},
        "excluded": {tid for tid, ex in rows if ex},
        "pull_end": _pull_end(user, day),
    }


def today_flag(task, m: dict) -> str:
    """'manual' | 'auto' | ''. 자동 담기는 내가 담당한 미완료 태스크에만 적용된다."""
    if task.pk in m["manual"]:
        return "manual"
    if (
        m["pull_end"] is not None
        and task.assignee_id == m["user_id"]
        and task.is_open
        and task.due_date is not None
        and task.due_date <= m["pull_end"]
        and task.pk not in m["excluded"]
    ):
        return "auto"
    return ""


def today_add(user, task, day: date | None = None) -> TodayItem:
    _require_member(user, task.project)
    day = day or today_kst()
    pos = (TodayItem.objects.filter(user=user, date=day).aggregate(m=Max("position"))["m"] or 0) + 1
    item, created = TodayItem.objects.get_or_create(
        user=user, task=task, date=day, defaults={"position": pos, "excluded": False}
    )
    if not created and item.excluded:
        item.excluded, item.position = False, pos
        item.save(update_fields=["excluded", "position"])
    return item


def today_exclude(user, task, day: date | None = None):
    """직접 담은 항목이면 빼고, 자동 담기 대상이면 오늘 하루 제외한다. 둘 다 같은 행 하나로 표현."""
    day = day or today_kst()
    TodayItem.objects.update_or_create(
        user=user, task=task, date=day, defaults={"excluded": True, "position": 0}
    )


def today_restore_excluded(user, day: date | None = None):
    day = day or today_kst()
    TodayItem.objects.filter(user=user, date=day, excluded=True).delete()


def today_set_auto_pull(user, days: int):
    if days not in dict(User.AUTO_PULL_CHOICES):
        raise ServiceError({"auto_pull_days": "0, 1, 3, 5, 7, 14 중 하나여야 합니다."})
    user.auto_pull_days = days
    user.save(update_fields=["auto_pull_days"])


def today_reorder(user, task_ids: list[int], day: date | None = None):
    day = day or today_kst()
    items = {i.task_id: i for i in TodayItem.objects.filter(user=user, date=day, excluded=False)}
    for pos, tid in enumerate(task_ids):
        if tid in items:
            TodayItem.objects.filter(pk=items[tid].pk).update(position=pos)


def today_move(user, task, direction: str, day: date | None = None):
    """직접 담은 항목끼리만 순서를 바꾼다. 자동 담긴 항목은 정렬 규칙을 따른다."""
    day = day or today_kst()
    ids = [i.task_id for i in TodayItem.objects.filter(user=user, date=day, excluded=False)]
    if task.pk not in ids:
        return
    idx = ids.index(task.pk)
    j = idx - 1 if direction == "up" else idx + 1
    if 0 <= j < len(ids):
        ids[idx], ids[j] = ids[j], ids[idx]
        today_reorder(user, ids, day)


def _rank(t):
    """자동 담긴 항목 정렬: 중요도 desc → 기한 asc → id."""
    return (-t.priority, t.due_date or date.max, t.pk)


def today_view(user, day: date | None = None) -> dict:
    """오늘 화면 데이터. 키: date, items, focus, done_today, auto_pull_days, counts.
    items 순서: 직접 담은 것(위치 순) → 자동 담긴 것(_rank) → 닫힌 것은 맨 뒤.
    각 Task에 auto_pulled(bool) 속성을 붙여 돌려준다."""
    day = day or today_kst()
    m = today_membership(user, day)
    manual = [
        i.task
        for i in today_items(user, day)
        .filter(excluded=False)
        .select_related("task__project", "task__assignee")
        .order_by("position", "id")
    ]
    # 팀에서 빠진 뒤에도 담당으로 남은 태스크가 새지 않도록 다른 읽기 경로와 같은 범위를 쓴다.
    mine = visible_tasks(user).filter(assignee=user)
    my_open = mine.filter(status__in=Task.OPEN)
    auto = []
    if m["pull_end"] is not None:
        auto = sorted(
            my_open.filter(due_date__lte=m["pull_end"]).exclude(pk__in=m["manual"] | m["excluded"]),
            key=_rank,
        )
    for t in manual:
        t.auto_pulled = False
    for t in auto:
        t.auto_pulled = True
    both = manual + auto
    items = [t for t in both if t.is_open] + [t for t in both if t.is_closed]
    start, end = kst_day_range(day)
    done_today = list(
        mine.filter(status="done", completed_at__gte=start, completed_at__lt=end).order_by("-completed_at")
    )
    week_start, _ = kst_day_range(day - timedelta(days=6))
    counts = {
        "today": len(items),
        "auto_pulled": len(auto),
        "excluded": len(m["excluded"]),
        "done_today": len(done_today),
        "done_7d": mine.filter(status="done", completed_at__gte=week_start, completed_at__lt=end).count(),
        "my_open": my_open.count(),
        "due_today": my_open.filter(due_date=day).count(),
        "overdue": my_open.filter(due_date__lt=day).count(),
        "review": my_open.filter(status="review").count(),
        "blocked": my_open.filter(status="blocked").count(),
    }
    return {
        "date": day,
        "items": items,
        "focus": next((t for t in items if t.is_open), None),
        "done_today": done_today,
        "auto_pull_days": user.auto_pull_days,
        "counts": counts,
    }


# ---------- 내 태스크 · 검색 ----------

def _due_preds(today: date) -> dict:
    monday, sunday = week_bounds(today)
    return {
        "overdue": lambda t: t.due_date is not None and t.due_date < today,
        "today": lambda t: t.due_date == today,
        "week": lambda t: t.due_date is not None and today < t.due_date <= sunday,
        "this_week": lambda t: t.due_date is not None and monday <= t.due_date <= sunday,
        "later": lambda t: t.due_date is not None and t.due_date > sunday,
        "none": lambda t: t.due_date is None,
    }


def me_view(user, *, member=None, group="due", due="", project=None, status="", priority="") -> dict:
    """내 태스크 화면 데이터. member: None=나, 0=팀 전체, User=다른 팀원.
    반환: {title, hint, groups, read_only, completion}
    groups[i]: {title, count, empty_text, flat, tasks, projects:[{project, done, total, pct, tasks}]}
    flat이면 tasks를 그대로, 아니면 projects의 하위 묶음으로 그린다."""
    today = today_kst()
    preds = _due_preds(today)
    completion = status in ("done_today", "done_7d")
    base = visible_tasks(user).filter(project__is_archived=False)
    if member is None:
        base = base.filter(assignee=user)
    elif not isinstance(member, int):
        base = base.filter(assignee=member)
    if completion:
        first = today if status == "done_today" else today - timedelta(days=6)
        start, _ = kst_day_range(first)
        _, end = kst_day_range(today)
        base = base.filter(status="done", completed_at__gte=start, completed_at__lt=end)
    else:
        base = base.filter(status__in=Task.OPEN)
    qs = base
    if project is not None:
        qs = qs.filter(project=project)
    if status and not completion:
        qs = qs.filter(status=status)
    if priority in Task.TIERS:
        lo, hi = Task.TIERS[priority]
        qs = qs.filter(priority__gte=lo, priority__lte=hi)
    tasks = sorted(qs, key=by_due)
    if due in preds:
        tasks = [t for t in tasks if preds[due](t)]

    def projects_of(ts):
        seen = {}
        for t in ts:
            seen.setdefault(t.project_id, t.project)
        return sorted(seen.values(), key=lambda p: p.name)

    def grp(title, pred, empty_text="", flat=False):
        ts = [t for t in tasks if pred(t)]
        g = {"title": title, "tasks": ts, "count": len(ts), "empty_text": empty_text, "flat": flat, "projects": []}
        if not flat:
            for p in projects_of(ts):
                st = project_stats(p)
                pct = round(st["done"] / st["total"] * 100) if st["total"] else 0
                g["projects"].append({
                    "project": p, "done": st["done"], "total": st["total"], "pct": pct,
                    "tasks": [t for t in ts if t.project_id == p.pk],
                })
        return g

    def eq(field, value):
        return lambda t: getattr(t, field) == value

    if completion:
        title = "오늘 완료" if status == "done_today" else "지난 7일 완료"
        groups = [grp(title, lambda t: True, "완료한 태스크가 없습니다.", flat=True)]
    elif group == "project":
        groups = [grp(p.name, eq("project_id", p.pk), flat=True) for p in projects_of(tasks)]
    elif group == "status":
        groups = [grp(label, eq("status", code)) for code, label in Task.STATUSES if code in Task.OPEN]
        groups = [g for g in groups if g["count"]]
    else:
        groups = [
            grp("기한 초과", preds["overdue"], "기한 초과 태스크 없음"),
            grp("오늘 마감", preds["today"], "오늘 마감 태스크 없음"),
            grp("이번 주 마감", preds["week"], "이번 주 마감 태스크 없음"),
            grp("그 이후", preds["later"]),
            grp("기한 미정", preds["none"]),
        ]
        groups = [g for g in groups if g["count"] or (g["empty_text"] and not due)]
    if not groups:
        groups = [{"title": "결과 없음", "tasks": [], "count": 0, "empty_text": "조건에 맞는 태스크가 없습니다.", "flat": True, "projects": []}]

    if member is None:
        title = "내 태스크"
    elif isinstance(member, int):
        title = "팀 전체 태스크"
    else:
        title = f"{member.display_name}의 태스크"
    hint = f"{'완료' if completion else '미완료'} {base.count()}건 · 결과 {len(tasks)}건"
    if member is not None:
        hint += " · 보기 전용"
    return {"title": title, "hint": hint, "groups": groups, "read_only": member is not None, "completion": completion}


def search(user, q: str, *, include_closed=False, include_archived=False):
    q = (q or "").strip()
    qs = visible_tasks(user)
    if not include_closed:
        qs = qs.filter(status__in=Task.OPEN)
    if not include_archived:
        qs = qs.filter(project__is_archived=False)
    if not q:
        return qs.none()
    cond = Q(title__icontains=q) | Q(project__name__icontains=q)
    num = q.upper().replace("TASK-", "")
    # isdigit()은 '²'에도 True다. int()가 받는 것은 isdecimal()뿐이다.
    if num.isdecimal():
        cond |= Q(pk=int(num))
    return qs.filter(cond).order_by("-id")[:100]
```

`me_view`의 `preds` 안 `lambda`는 함수 인자 `today`를 닫아 두므로 늦은 바인딩 문제가 없다. `eq()`도 같은 이유로 헬퍼로 뺐다.

### 3.4 `core/tasks/brief.py` (API·보고서가 같이 쓰는 요약 dict)

```python
from django.conf import settings


def user_brief(u) -> dict | None:
    if u is None:
        return None
    return {"id": u.pk, "display_name": u.display_name, "discord_user_id": u.discord_user_id}


def task_brief(t) -> dict:
    return {
        "id": t.pk,
        "number": t.number,
        "title": t.title,
        "project": {"id": t.project_id, "name": t.project.name, "team_id": t.project.team_id},
        "assignee": user_brief(t.assignee),
        "status": t.status,
        "priority": t.priority,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "stop_reason": t.stop_reason,
        "next_action": t.next_action,
        "url": f"{settings.SITE_URL}/tasks/{t.pk}",
    }
```

### 3.5 검증

```bash
uv run python manage.py check
uv run ruff check .
```

오류 0. 테스트는 01-5에서 한꺼번에 쓴다. 다만 Step 3 커밋 전에 최소 확인으로 Django shell에서 다음이 동작해야 한다.

```bash
uv run python manage.py shell -c "
from accounts.models import User
from teams.services import create_team
from projects.services import create_project
from tasks.services import create_task, transition, today_view
from datetime import date, timedelta
u = User.objects.create_user('u1', password='pw12345678', display_name='유저1')
t = create_team('산돌이', '', u)
p = create_project(team=t, name='학식 API', actor=u, owners=[u])
task = create_task(project=p, title='메뉴 누락 개선', actor=u, source='web', due_date=date.today()+timedelta(days=3), priority=9)
print(len(today_view(u)['items']))
task = transition(task, 'doing', actor=u, source='web', expected_version=1)
task = transition(task, 'blocked', actor=u, source='web', reason='서류 대기', expected_version=2)
task = transition(task, 'done', actor=u, source='web', expected_version=3)
print(task.number, task.status, task.version, task.stop_reason == '', task.completed_at is not None)
"
```

출력: `1` (기한 3일 이내라 자동 담김), 그다음 `TASK-1 done 4 True True`.

커밋: `step 3: services layer`

---

## Step 4. reports (숫자 집계, LLM 없음)

### 4.1 `core/reports/services.py`

```python
from datetime import date, timedelta

from django.db.models import Count, Q

from common.dates import kst_week_range, today_kst, week_bounds
from tasks.brief import task_brief, user_brief
from tasks.models import ChangeLog, Task


def _open_qs(team):
    return Task.objects.filter(project__team=team, project__is_archived=False, status__in=Task.OPEN)


def team_status(team) -> dict:
    """팀 현황 지표. 키: counts, by_project, by_assignee, projects_without_owner"""
    today = today_kst()
    monday, sunday = week_bounds(today)
    open_qs = _open_qs(team)
    counts = {
        "open": open_qs.count(),
        "overdue": open_qs.filter(due_date__lt=today).count(),
        "due_this_week": open_qs.filter(due_date__gte=monday, due_date__lte=sunday).count(),
        "review": open_qs.filter(status="review").count(),
        "blocked": open_qs.filter(status="blocked").count(),
        "no_due": open_qs.filter(due_date__isnull=True).count(),
    }
    projects = (
        team.projects.filter(is_archived=False)
        .prefetch_related("owners")
        .annotate(
            open_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN)),
            overdue_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN, tasks__due_date__lt=today)),
            review_count=Count("tasks", filter=Q(tasks__status="review")),
            blocked_count=Count("tasks", filter=Q(tasks__status="blocked")),
            done_count=Count("tasks", filter=Q(tasks__status="done")),
            total_count=Count("tasks", filter=~Q(tasks__status="cancelled")),
        )
    )
    by_project = [
        {
            "id": p.pk, "name": p.name, "status": p.status,
            "owners": [user_brief(u) for u in p.owners.all()],
            "open": p.open_count, "overdue": p.overdue_count, "review": p.review_count,
            "blocked": p.blocked_count, "done": p.done_count, "total": p.total_count,
        }
        for p in projects
    ]
    by_assignee = list(
        open_qs.values("assignee_id", "assignee__display_name")
        .annotate(
            open=Count("id"),
            overdue=Count("id", filter=Q(due_date__lt=today)),
            review=Count("id", filter=Q(status="review")),
            blocked=Count("id", filter=Q(status="blocked")),
        )
        .order_by("-open")
    )
    projects_without_owner = list(
        team.projects.filter(is_archived=False, owners__isnull=True).values("id", "name")
    )
    return {
        "counts": counts,
        "by_project": by_project,
        "by_assignee": by_assignee,
        "projects_without_owner": projects_without_owner,
    }


def weekly(team, week_start: date) -> dict:
    """주간 집계. week_start는 월요일이어야 한다."""
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    start, end = kst_week_range(week_start)
    period_end = week_start + timedelta(days=7)
    this_monday, this_sunday = week_bounds(period_end)
    today = today_kst()

    team_task_ids = Task.objects.filter(project__team=team).values("id")
    logs = ChangeLog.objects.filter(
        target_type="task", field="status", target_id__in=team_task_ids,
        created_at__gte=start, created_at__lt=end,
    )
    completed_ids = set(logs.filter(new_value="done").values_list("target_id", flat=True))
    reopened_ids = set(
        logs.filter(old_value__in=["done", "cancelled"], new_value__in=["todo", "doing"])
        .values_list("target_id", flat=True)
    )

    def briefs(ids):
        qs = Task.objects.filter(pk__in=ids).select_related("project", "assignee").order_by("project__name", "id")
        return [task_brief(t) for t in qs]

    open_qs = _open_qs(team).select_related("project", "assignee")
    due_this_week = [task_brief(t) for t in open_qs.filter(due_date__gte=this_monday, due_date__lte=this_sunday).order_by("due_date", "id")]
    overdue = [task_brief(t) for t in open_qs.filter(due_date__lt=today).order_by("due_date", "id")]
    blocked = [task_brief(t) for t in open_qs.filter(status="blocked").order_by("id")]

    by_project = []
    for p in team.projects.filter(is_archived=False).order_by("name"):
        p_ids = set(Task.objects.filter(project=p).values_list("id", flat=True))
        by_project.append({
            "project": {"id": p.pk, "name": p.name, "status": p.status},
            "completed": len(completed_ids & p_ids),
            "reopened": len(reopened_ids & p_ids),
            "open": open_qs.filter(project=p).count(),
            "overdue": open_qs.filter(project=p, due_date__lt=today).count(),
            "blocked": open_qs.filter(project=p, status="blocked").count(),
        })

    return {
        "team": {"id": team.pk, "name": team.name},
        "period_start": week_start.isoformat(),
        "period_end": period_end.isoformat(),
        "completed": briefs(completed_ids),
        "reopened": briefs(reopened_ids),
        "due_this_week": due_this_week,
        "overdue": overdue,
        "blocked": blocked,
        "by_project": by_project,
        "counts": {
            "completed": len(completed_ids),
            "reopened": len(reopened_ids),
            "due_this_week": len(due_this_week),
            "overdue": len(overdue),
            "blocked": len(blocked),
            "open": open_qs.count(),
            "review": open_qs.filter(status="review").count(),
            "no_due": open_qs.filter(due_date__isnull=True).count(),
        },
        "members": [user_brief(u) for u in team.members.filter(is_active=True).order_by("display_name")],
    }
```

`weekly()`가 돌려주는 dict의 **키 이름과 구조는 Discord 서비스·MCP 서버와의 계약**이다. 최상위 키 11개, `counts` 키 8개. 바꾸지 않는다.

### 4.2 검증

```bash
uv run python manage.py check
uv run ruff check .
```

커밋: `step 4: reports services`

다음: [GUIDE-01-core-3-api.md](GUIDE-01-core-3-api.md)
