# 구현 지시서 01-3: core — HTTP API (Step 5)

이전: [01-2](GUIDE-01-core-2-services.md). Django Ninja로 만든다. 이 API는 MCP 서버·Discord 서비스와의 **유일한 계약**이다. 경로, 필드 이름, 응답 모양을 바꾸지 않는다.

개정 2026-09-10: 상태 7개, 중요도 정수, 프로젝트 `owners`, `stop_reason`·`notes`, `/block`·`/comments` 삭제, `/extend` 추가, 오늘 목록 제외·복원·설정.

파일 구성:

```
core/api/
  api.py          NinjaAPI 인스턴스, 예외 처리, 라우터 등록
  auth.py         Bearer 토큰 인증
  context.py      요청에서 actor/source/token 꺼내기, 공통 헬퍼
  schemas.py      입력·출력 스키마
  serialize.py    모델 → dict
  routers/
    __init__.py
    me.py teams.py projects.py tasks.py today.py reports.py integrations.py
```

---

## 5.1 `core/api/auth.py`

```python
from ninja.errors import HttpError
from ninja.security import HttpBearer

from accounts.models import ApiToken

WRITE_EXEMPT_PREFIX = "/api/integrations/"


class TokenAuth(HttpBearer):
    def authenticate(self, request, token):
        t = ApiToken.authenticate(token)
        if t is None:
            return None
        if (
            t.scope == "read"
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and not request.path.startswith(WRITE_EXEMPT_PREFIX)
        ):
            raise HttpError(403, "읽기 전용 토큰입니다.")
        request.api_token = t
        return t.user
```

## 5.2 `core/api/context.py`

```python
from ninja.errors import HttpError

from tasks.services import get_visible_task
from teams.models import Team
from teams.services import is_member


def ctx(request) -> dict:
    """services 함수에 넘길 actor/source/token."""
    token = getattr(request, "api_token", None)
    if token is None:
        source = "web"
    elif request.headers.get("X-Source", "").lower() == "mcp":
        source = "mcp"
    else:
        source = "api"
    return {"actor": request.auth, "source": source, "token": token}


def idem_key(request) -> str | None:
    key = request.headers.get("Idempotency-Key")
    return key[:100] if key else None


def task_or_404(request, task_id: int):
    task = get_visible_task(request.auth, task_id)
    if task is None:
        raise HttpError(404, "태스크를 찾을 수 없습니다.")
    return task


def team_or_404(request, team_id: int):
    team = Team.objects.filter(pk=team_id).first()
    if team is None or not is_member(request.auth, team):
        raise HttpError(404, "팀을 찾을 수 없습니다.")
    return team


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)
```

## 5.3 `core/api/schemas.py`

```python
from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Schema
from pydantic import Field

Status = Literal["todo", "doing", "paused", "blocked", "review", "done", "cancelled"]
Priority = Annotated[int, Field(ge=1, le=10)]
ProjectStatus = Literal["preparing", "on_hold", "waiting", "active", "paused", "done", "stopped", "eol"]


class UserBrief(Schema):
    id: int
    display_name: str
    discord_user_id: str | None = None


class ProjectBrief(Schema):
    id: int
    name: str
    team_id: int


class TaskBriefOut(Schema):
    id: int
    number: str
    title: str
    project: ProjectBrief
    assignee: UserBrief
    status: Status
    priority: int
    due_date: date | None
    stop_reason: str
    next_action: str
    url: str


class ChecklistItemOut(Schema):
    id: int
    text: str
    is_done: bool
    position: int


class ChecklistItemIn(Schema):
    text: str
    is_done: bool = False


class LinkOut(Schema):
    id: int
    title: str
    url: str
    kind: str


class TaskOut(TaskBriefOut):
    description: str
    done_when: str
    notes: str
    no_due_reason: str
    stopped_at: datetime | None
    completed_at: datetime | None
    version: int
    created_by: UserBrief
    created_at: datetime
    updated_at: datetime
    checklist: list[ChecklistItemOut]
    checklist_done: int
    checklist_total: int
    links: list[LinkOut]


class TaskCreateIn(Schema):
    project_id: int
    title: str
    assignee_id: int | None = None
    description: str = ""
    done_when: str = ""
    next_action: str = ""
    priority: Priority = 5
    due_date: date | None = None
    no_due_reason: str = ""
    checklist: list[ChecklistItemIn] | None = None


class TaskPatchIn(Schema):
    version: int
    title: str | None = None
    description: str | None = None
    done_when: str | None = None
    next_action: str | None = None
    notes: str | None = None
    assignee_id: int | None = None
    project_id: int | None = None
    priority: Priority | None = None
    due_date: date | None = None
    no_due_reason: str | None = None
    stop_reason: str | None = None
    checklist: list[ChecklistItemIn] | None = None


class TransitionIn(Schema):
    status: Status
    reason: str = ""
    version: int


class ExtendIn(Schema):
    due_date: date
    reason: str
    version: int


class ChangeLogOut(Schema):
    id: int
    field: str
    old_value: str
    new_value: str
    note: str
    actor: UserBrief
    source: str
    created_at: datetime


class TaskListOut(Schema):
    items: list[TaskBriefOut]
    total: int
    limit: int
    offset: int


class ProjectStats(Schema):
    total: int
    open: int
    overdue: int
    review: int
    blocked: int
    done: int


class ProjectOut(Schema):
    id: int
    team_id: int
    name: str
    purpose: str
    owners: list[UserBrief]
    status: ProjectStatus
    status_label: str
    is_archived: bool
    version: int
    stats: ProjectStats
    links: list[LinkOut]
    url: str


class ProjectCreateIn(Schema):
    team_id: int
    name: str
    purpose: str = ""
    owner_ids: list[int] = []
    status: ProjectStatus = "preparing"


class ProjectPatchIn(Schema):
    version: int
    name: str | None = None
    purpose: str | None = None
    owner_ids: list[int] | None = None
    status: ProjectStatus | None = None


class TeamBrief(Schema):
    id: int
    name: str
    purpose: str
    role: str


class MeOut(Schema):
    id: int
    username: str
    display_name: str
    discord_user_id: str | None
    auto_pull_days: int
    teams: list[TeamBrief]


class TeamOut(Schema):
    id: int
    name: str
    purpose: str
    role: str
    projects: list[ProjectOut]


class InviteIn(Schema):
    days: int = 7


class InviteOut(Schema):
    id: int
    url: str
    expires_at: datetime
    use_count: int
    revoked_at: datetime | None


class TodayItemOut(TaskBriefOut):
    auto_pulled: bool


class TodayOut(Schema):
    date: date
    items: list[TodayItemOut]
    focus: TaskBriefOut | None
    done_today: list[TaskBriefOut]
    auto_pull_days: int
    counts: dict


class TodayAddIn(Schema):
    task_id: int


class TodayOrderIn(Schema):
    task_ids: list[int]


class TodaySettingsIn(Schema):
    auto_pull_days: int


class StatusIn(Schema):
    ok: bool
    detail: dict = {}


class ErrorOut(Schema):
    detail: dict | str


class ConflictOut(Schema):
    detail: str
    latest: dict
```

## 5.4 `core/api/serialize.py`

```python
from django.conf import settings

from projects.services import project_stats
from tasks.brief import task_brief, user_brief


def link_out(link) -> dict:
    return {"id": link.pk, "title": link.title, "url": link.url, "kind": link.kind}


def changelog_out(log) -> dict:
    return {
        "id": log.pk, "field": log.field, "old_value": log.old_value,
        "new_value": log.new_value, "note": log.note, "actor": user_brief(log.actor),
        "source": log.source, "created_at": log.created_at,
    }


def task_out(t) -> dict:
    items = list(t.checklist.all())
    d = task_brief(t)
    d.update({
        "description": t.description,
        "done_when": t.done_when,
        "notes": t.notes,
        "no_due_reason": t.no_due_reason,
        "stopped_at": t.stopped_at,
        "completed_at": t.completed_at,
        "version": t.version,
        "created_by": user_brief(t.created_by),
        "created_at": t.created_at,
        "updated_at": t.updated_at,
        "checklist": [
            {"id": i.pk, "text": i.text, "is_done": i.is_done, "position": i.position} for i in items
        ],
        "checklist_done": sum(1 for i in items if i.is_done),
        "checklist_total": len(items),
        "links": [link_out(link) for link in t.links.all()],
    })
    return d


def project_out(p) -> dict:
    return {
        "id": p.pk, "team_id": p.team_id, "name": p.name, "purpose": p.purpose,
        "owners": [user_brief(u) for u in p.owners.all()],
        "status": p.status, "status_label": p.status_label,
        "is_archived": p.is_archived, "version": p.version,
        "stats": project_stats(p),
        "links": [link_out(link) for link in p.links.all()],
        "url": f"{settings.SITE_URL}/projects/{p.pk}",
    }


def invite_out(inv) -> dict:
    return {
        "id": inv.pk, "url": f"{settings.SITE_URL}{inv.path}", "expires_at": inv.expires_at,
        "use_count": inv.use_count, "revoked_at": inv.revoked_at,
    }
```

## 5.5 `core/api/api.py` (임시 파일을 이걸로 교체)

```python
from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI
from ninja.security import django_auth
from ninja.throttling import AuthRateThrottle

from common.errors import ConflictError, ServiceError

from .auth import TokenAuth
from .routers import integrations, me, projects, reports, tasks, teams, today
from .serialize import project_out, task_out

api = NinjaAPI(
    title="Sandol PM API",
    version="1",
    auth=[django_auth, TokenAuth()],
    throttle=[AuthRateThrottle("60/m")],
    docs_decorator=login_required,
    urls_namespace="api",
)


@api.exception_handler(ServiceError)
def _service_error(request, exc):
    return api.create_response(request, {"detail": exc.errors}, status=400)


@api.exception_handler(ConflictError)
def _conflict(request, exc):
    latest = exc.latest
    data = task_out(latest) if hasattr(latest, "assignee") else project_out(latest)
    return api.create_response(request, {"detail": "conflict", "latest": data}, status=409)


api.add_router("/", me.router)
api.add_router("/teams", teams.router)
api.add_router("/projects", projects.router)
api.add_router("/tasks", tasks.router)
api.add_router("/today", today.router)
api.add_router("/reports", reports.router)
api.add_router("/integrations", integrations.router)
```

`core/api/routers/__init__.py`는 빈 파일.

## 5.6 라우터

### `core/api/routers/me.py`

```python
from ninja import Router

from teams.models import Membership

from ..schemas import MeOut

router = Router(tags=["me"])


@router.get("/me", response=MeOut)
def me(request):
    u = request.auth
    memberships = Membership.objects.filter(user=u).select_related("team").order_by("team__name")
    return {
        "id": u.pk, "username": u.username, "display_name": u.display_name,
        "discord_user_id": u.discord_user_id, "auto_pull_days": u.auto_pull_days,
        "teams": [
            {"id": m.team_id, "name": m.team.name, "purpose": m.team.purpose, "role": m.role}
            for m in memberships
        ],
    }
```

### `core/api/routers/teams.py`

```python
from ninja import Router
from ninja.errors import HttpError

from reports.services import team_status
from tasks.brief import user_brief
from teams.models import Invite, Membership
from teams.services import create_invite, revoke_invite

from ..context import ctx, team_or_404
from ..schemas import ErrorOut, InviteIn, InviteOut, TeamOut, UserBrief
from ..serialize import invite_out, project_out

router = Router(tags=["teams"])


@router.get("/{team_id}", response=TeamOut)
def get_team(request, team_id: int):
    team = team_or_404(request, team_id)
    role = Membership.objects.get(team=team, user=request.auth).role
    projects = team.projects.filter(is_archived=False).prefetch_related("owners")
    return {
        "id": team.pk, "name": team.name, "purpose": team.purpose, "role": role,
        "projects": [project_out(p) for p in projects],
    }


@router.get("/{team_id}/members", response=list[UserBrief])
def members(request, team_id: int):
    team = team_or_404(request, team_id)
    return [user_brief(u) for u in team.members.filter(is_active=True).order_by("display_name")]


@router.get("/{team_id}/status", response=dict)
def status(request, team_id: int):
    return team_status(team_or_404(request, team_id))


@router.post("/{team_id}/invites", response={201: InviteOut, 400: ErrorOut})
def create_invite_ep(request, team_id: int, payload: InviteIn):
    team = team_or_404(request, team_id)
    inv = create_invite(team, ctx(request)["actor"], days=payload.days)
    return 201, invite_out(inv)


@router.delete("/invites/{invite_id}", response={204: None})
def delete_invite(request, invite_id: int):
    inv = Invite.objects.filter(pk=invite_id).select_related("team").first()
    if inv is None:
        raise HttpError(404, "초대를 찾을 수 없습니다.")
    team_or_404(request, inv.team_id)
    revoke_invite(inv, ctx(request)["actor"])
    return 204, None
```

`api.py`에서 `/teams` 라우터에 붙였으므로 실제 경로는 `DELETE /api/teams/invites/{id}`가 된다. 이것이 의도한 경로다.

### `core/api/routers/projects.py`

```python
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from projects.models import Project
from projects.services import create_project, update_project
from teams.services import teams_of

from ..context import ctx, team_or_404
from ..schemas import ConflictOut, ErrorOut, ProjectCreateIn, ProjectOut, ProjectPatchIn
from ..serialize import project_out

router = Router(tags=["projects"])


def _visible(request):
    return Project.objects.filter(team__in=teams_of(request.auth)).select_related("team").prefetch_related("owners")


def _project_or_404(request, project_id: int) -> Project:
    p = _visible(request).filter(pk=project_id).first()
    if p is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    return p


def _owners(ids: list[int]) -> list[User]:
    users = list(User.objects.filter(pk__in=ids))
    if len(users) != len(set(ids)):
        raise HttpError(400, "관리자를 찾을 수 없습니다.")
    return users


@router.get("", response=list[ProjectOut])
def list_projects(request, team: int | None = None, include_archived: bool = False):
    qs = _visible(request)
    if team is not None:
        qs = qs.filter(team_id=team)
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return [project_out(p) for p in qs.order_by("team__name", "name")]


@router.get("/{project_id}", response=ProjectOut)
def get_project(request, project_id: int):
    return project_out(_project_or_404(request, project_id))


@router.post("", response={201: ProjectOut, 400: ErrorOut})
def create_project_ep(request, payload: ProjectCreateIn):
    team = team_or_404(request, payload.team_id)
    p = create_project(
        team=team, name=payload.name, purpose=payload.purpose,
        owners=_owners(payload.owner_ids), status=payload.status, **ctx(request),
    )
    return 201, project_out(p)


@router.patch("/{project_id}", response={200: ProjectOut, 400: ErrorOut, 409: ConflictOut})
def patch_project(request, project_id: int, payload: ProjectPatchIn):
    p = _project_or_404(request, project_id)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    if "owner_ids" in data:
        data["owners"] = _owners(data.pop("owner_ids") or [])
    p = update_project(p, data, expected_version=version, **ctx(request))
    return project_out(p)
```

### `core/api/routers/tasks.py`

```python
from datetime import date

from django.db.models import F
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from projects.models import Project
from tasks.brief import task_brief
from tasks.models import ChangeLog, Task
from tasks.services import (
    create_task, extend_due, replace_checklist, transition, update_task, visible_tasks,
)
from teams.services import teams_of

from ..context import clamp_page, ctx, idem_key, task_or_404
from ..schemas import (
    ChangeLogOut, ConflictOut, ErrorOut, ExtendIn, TaskCreateIn, TaskListOut, TaskOut,
    TaskPatchIn, TransitionIn,
)
from ..serialize import changelog_out, task_out

router = Router(tags=["tasks"])


@router.get("", response=TaskListOut)
def list_tasks(
    request,
    team: int | None = None,
    project: int | None = None,
    assignee: int | None = None,
    status: str | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    qs = visible_tasks(request.auth)
    if team is not None:
        qs = qs.filter(project__team_id=team)
    if project is not None:
        qs = qs.filter(project_id=project)
    if assignee is not None:
        qs = qs.filter(assignee_id=assignee)
    if status:
        values = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in values if s not in dict(Task.STATUSES)]
        if bad:
            raise HttpError(400, f"알 수 없는 상태: {', '.join(bad)}")
        qs = qs.filter(status__in=values)
    if due_from:
        qs = qs.filter(due_date__gte=due_from)
    if due_to:
        qs = qs.filter(due_date__lte=due_to)
    if q:
        qs = qs.filter(title__icontains=q)
    if not include_archived:
        qs = qs.filter(project__is_archived=False)
    limit, offset = clamp_page(limit, offset)
    # nulls_last를 명시해야 SQLite(기한 미정이 앞)와 Postgres(뒤)가 같아지고 by_due()와도 맞는다.
    qs = qs.order_by(F("due_date").asc(nulls_last=True), "id")
    total = qs.count()
    return {
        "items": [task_brief(t) for t in qs[offset : offset + limit]],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/{task_id}", response=TaskOut)
def get_task(request, task_id: int):
    return task_out(task_or_404(request, task_id))


@router.get("/{task_id}/history", response=list[ChangeLogOut])
def history(request, task_id: int):
    task = task_or_404(request, task_id)
    logs = ChangeLog.objects.filter(target_type="task", target_id=task.pk).select_related("actor")
    return [changelog_out(log) for log in logs]


@router.post("", response={201: TaskOut, 400: ErrorOut})
def create_task_ep(request, payload: TaskCreateIn):
    project = Project.objects.filter(pk=payload.project_id, team__in=teams_of(request.auth)).first()
    if project is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    assignee = None
    if payload.assignee_id:
        assignee = User.objects.filter(pk=payload.assignee_id).first()
        if assignee is None:
            raise HttpError(400, "담당자를 찾을 수 없습니다.")
    c = ctx(request)
    task = create_task(
        project=project, title=payload.title, assignee=assignee,
        description=payload.description, done_when=payload.done_when,
        next_action=payload.next_action, priority=payload.priority,
        due_date=payload.due_date, no_due_reason=payload.no_due_reason,
        idempotency_key=idem_key(request), **c,
    )
    if payload.checklist is not None and not task.checklist.exists():
        replace_checklist(task, [i.dict() for i in payload.checklist], actor=c["actor"])
    return 201, task_out(task)


@router.patch("/{task_id}", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def patch_task(request, task_id: int, payload: TaskPatchIn):
    task = task_or_404(request, task_id)
    c = ctx(request)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    checklist = data.pop("checklist", None)
    if "assignee_id" in data:
        aid = data.pop("assignee_id")
        data["assignee"] = User.objects.filter(pk=aid).first() if aid else None
    if "project_id" in data:
        pid = data.pop("project_id")
        data["project"] = Project.objects.filter(pk=pid, team__in=teams_of(request.auth)).first()
        if data["project"] is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if data:
        task = update_task(task, data, expected_version=version, **c)
    if checklist is not None:
        replace_checklist(task, checklist, actor=c["actor"])
    return task_out(task)


@router.post("/{task_id}/transition", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def transition_ep(request, task_id: int, payload: TransitionIn):
    task = task_or_404(request, task_id)
    task = transition(
        task, payload.status, reason=payload.reason, expected_version=payload.version, **ctx(request)
    )
    return task_out(task)


@router.post("/{task_id}/extend", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def extend_ep(request, task_id: int, payload: ExtendIn):
    task = task_or_404(request, task_id)
    task = extend_due(
        task, payload.due_date, payload.reason, expected_version=payload.version, **ctx(request)
    )
    return task_out(task)
```

`PATCH`로 `title/description/done_when/next_action/notes`만 바꾸면 `version` 검사 없이 저장되고 `version`이 오르지 않는다(자동 저장 필드). 팀 데이터 필드가 하나라도 있으면 `version`이 검사된다.

### `core/api/routers/today.py`

```python
from ninja import Router

from tasks.brief import task_brief
from tasks.services import (
    today_add, today_exclude, today_reorder, today_restore_excluded, today_set_auto_pull,
    today_view,
)

from ..context import task_or_404
from ..schemas import ErrorOut, TodayAddIn, TodayOrderIn, TodayOut, TodaySettingsIn

router = Router(tags=["today"])


def _out(user) -> dict:
    v = today_view(user)
    return {
        "date": v["date"],
        "items": [{**task_brief(t), "auto_pulled": t.auto_pulled} for t in v["items"]],
        "focus": task_brief(v["focus"]) if v["focus"] else None,
        "done_today": [task_brief(t) for t in v["done_today"]],
        "auto_pull_days": v["auto_pull_days"],
        "counts": v["counts"],
    }


@router.get("", response=TodayOut)
def get_today(request):
    return _out(request.auth)


@router.post("", response=TodayOut)
def add(request, payload: TodayAddIn):
    today_add(request.auth, task_or_404(request, payload.task_id))
    return _out(request.auth)


@router.delete("/excluded", response=TodayOut)
def restore(request):
    today_restore_excluded(request.auth)
    return _out(request.auth)


@router.delete("/{task_id}", response=TodayOut)
def exclude(request, task_id: int):
    today_exclude(request.auth, task_or_404(request, task_id))
    return _out(request.auth)


@router.patch("/order", response=TodayOut)
def order(request, payload: TodayOrderIn):
    today_reorder(request.auth, payload.task_ids)
    return _out(request.auth)


@router.patch("/settings", response={200: TodayOut, 400: ErrorOut})
def settings_ep(request, payload: TodaySettingsIn):
    today_set_auto_pull(request.auth, payload.auto_pull_days)
    return _out(request.auth)
```

`DELETE /today/excluded`를 `DELETE /today/{task_id}`보다 **먼저** 등록한다. `task_id`는 `int` 변환기라 "excluded"에 매칭되지 않지만, 순서를 지켜 두면 헷갈리지 않는다.

### `core/api/routers/reports.py`

```python
from datetime import date

from ninja import Router
from ninja.errors import HttpError

from common.dates import last_week_start
from reports.services import weekly

from ..context import team_or_404

router = Router(tags=["reports"])


@router.get("/weekly", response=dict)
def weekly_ep(request, team: int, week_start: date | None = None):
    t = team_or_404(request, team)
    ws = week_start or last_week_start()
    if ws.weekday() != 0:
        raise HttpError(400, "week_start는 월요일이어야 합니다.")
    return weekly(t, ws)
```

### `core/api/routers/integrations.py`

```python
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from ..models import IntegrationStatus
from ..schemas import StatusIn

router = Router(tags=["integrations"])
ALLOWED = {"discord", "mcp"}


@router.post("/{name}/status", response={204: None})
def report_status(request, name: str, payload: StatusIn):
    if name not in ALLOWED:
        raise HttpError(404, "알 수 없는 통합 이름입니다.")
    IntegrationStatus.objects.update_or_create(
        name=name,
        defaults={"last_run_at": timezone.now(), "ok": payload.ok, "detail": payload.detail},
    )
    return 204, None
```

---

## 5.7 엔드포인트 요약과 예시

| 메서드·경로 | 성공 | 실패 |
|---|---|---|
| `GET /api/me` | 200 `MeOut` | 401 |
| `GET /api/teams/{id}` | 200 `TeamOut` | 404 |
| `GET /api/teams/{id}/members` | 200 `[UserBrief]` | 404 |
| `GET /api/teams/{id}/status` | 200 dict (`team_status`) | 404 |
| `POST /api/teams/{id}/invites` `{days}` | 201 `InviteOut` | 400(관리자 아님) |
| `DELETE /api/teams/invites/{id}` | 204 | 404 |
| `GET /api/projects?team=&include_archived=` | 200 `[ProjectOut]` | |
| `GET /api/projects/{id}` | 200 `ProjectOut` | 404 |
| `POST /api/projects` `{team_id, name, purpose, owner_ids, status}` | 201 | 400 |
| `PATCH /api/projects/{id}` (version 필수) | 200 | 400, 409 |
| `GET /api/tasks?team=&project=&assignee=&status=&due_from=&due_to=&q=&include_archived=&limit=&offset=` | 200 `TaskListOut` | 400(상태값 오류) |
| `GET /api/tasks/{id}` | 200 `TaskOut` | 404 |
| `GET /api/tasks/{id}/history` | 200 `[ChangeLogOut]` | 404 |
| `POST /api/tasks` (헤더 `Idempotency-Key` 선택) | 201 `TaskOut` | 400, 404 |
| `PATCH /api/tasks/{id}` (version 필수) | 200 | 400, 404, 409 |
| `POST /api/tasks/{id}/transition` `{status, reason, version}` | 200 | 400, 409 |
| `POST /api/tasks/{id}/extend` `{due_date, reason, version}` | 200 | 400, 409 |
| `GET /api/today` · `POST /api/today` `{task_id}` · `DELETE /api/today/{task_id}`(오늘 제외) · `DELETE /api/today/excluded`(제외 복원) · `PATCH /api/today/order` `{task_ids}` · `PATCH /api/today/settings` `{auto_pull_days}` | 200 `TodayOut` | 400, 404 |
| `GET /api/reports/weekly?team=&week_start=` | 200 dict (`weekly`) | 400, 404 |
| `POST /api/integrations/{name}/status` `{ok, detail}` | 204 | 404 |

공통:

- 인증 실패 401. 읽기 토큰으로 쓰기 요청 403.
- 검증 실패 400 본문: `{"detail": {"필드": "메시지"}}`.
- 충돌 409 본문: `{"detail": "conflict", "latest": <TaskOut 또는 ProjectOut>}`.
- 헤더 `X-Source: mcp`가 있고 토큰 인증이면 변경 이력 `source`가 `mcp`로 기록된다.
- 막힘·일시정지는 `transition`으로 한다: `{"status":"blocked","reason":"서류 대기","version":3}`. 이미 멈춘 태스크의 사유만 고치려면 `PATCH {"stop_reason": "...", "version": n}`.
- 진행 메모는 `PATCH {"notes": "..."}`로 통째로 바꾼다(덧붙이기는 클라이언트가 읽어서 이어 붙인다).

예시 (curl):

```bash
curl -s -H "Authorization: Bearer pm_..." "http://localhost:8000/api/tasks?team=1&status=todo,doing,paused,blocked,review&limit=20"
curl -s -H "Authorization: Bearer pm_..." -H "Content-Type: application/json" \
  -X POST http://localhost:8000/api/tasks/12/transition -d '{"status":"done","version":3}'
```

---

## 5.8 검증

```bash
uv run python manage.py check
uv run ruff check .
uv run python manage.py runserver
```

브라우저에서 admin 로그인 후 `http://127.0.0.1:8000/api/docs`가 열리고 5.7 표의 엔드포인트가 전부 보이면 통과. shell에서 토큰을 만들어 curl로 `GET /api/me`가 200을 돌려주는지 확인한다.

```bash
uv run python manage.py shell -c "
from accounts.models import User, ApiToken
u = User.objects.get(username='u1')
t, raw = ApiToken.issue(u, 'test', 'write')
print(raw)
"
```

커밋: `step 5: http api`

다음: [GUIDE-01-core-4-web.md](GUIDE-01-core-4-web.md)
