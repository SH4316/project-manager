# 구현 지시서 V2-01: 조직 → 팀 → 멤버 (1단계)

목표: 지금의 `Team`을 **조직**으로 올리고, 그 안에 **팀**(사람 묶음)을 새로 만든다. 멤버는 여러 팀에 속한다. 프로젝트는 조직 소속이고 담당 팀을 여럿 가진다.

이 단계는 **화면을 새로 만들지 않는다.** 이름과 계층만 바꾸고, 기존 화면이 전부 그대로 동작하면 끝이다. 화면 개편은 `GUIDE-V2-02`에서 한다.

> **가장 중요한 것 하나:** 팀은 **가시성을 제한하지 않는다.** 조직 멤버는 조직의 모든 프로젝트와 태스크를 본다. 팀은 부하 현황 필터, 프로젝트 담당 표시, GitHub 팀 연결에만 쓰인다. 어디에도 `team__in=` 으로 태스크를 거르는 코드를 넣지 않는다.

---

## 1. 개명 대조표

작업 내내 이 표를 옆에 둔다. 왼쪽은 **기존 코드와 `GUIDE-01~04`의 용어**이고, 그 `Team`은 전부 조직을 뜻한다.

| 이전 | 이후 |
|---|---|
| `core/teams/` 앱 | `core/orgs/` 앱 |
| `teams.Team` | `orgs.Organization` |
| `teams.Membership` | `orgs.OrgMembership` |
| `teams.Invite` (team FK) | `orgs.Invite` (org FK) |
| — | **`orgs.Team`, `orgs.TeamMembership`** (신규, 사람 묶음) |
| `teams.services.teams_of(user)` | `orgs.services.orgs_of(user)` |
| `is_member(user, team)` · `is_admin` · `require_admin` | 인자 이름만 `org`로 |
| `create_team(name, purpose, actor)` | `create_org(name, purpose, actor)` |
| `Project.team` | `Project.org` + **`Project.teams`** (M2M) |
| `reports.services.team_status(team)` | `org_status(org)` |
| `web.views.common.current_team` | `current_org` |
| `web.views.common.team_or_404` | `org_or_404` |
| 세션 키 `team_id` | `org_id` |
| `request.user.teams` | `request.user.orgs` |
| URL `/team` · `/teams/<id>` · `/teams/<id>/members` | `/org` · `/orgs/<id>` · `/orgs/<id>/members` |
| URL 이름 `team` · `team_list` · `team_detail` · `team_new` · `team_members` | `org` · `org_list` · `org_detail` · `org_new` · `org_members` |
| 템플릿 폴더 `templates/teams/` | `templates/orgs/` |
| API `/api/teams/*` | `/api/orgs/*` |
| API 쿼리 `?team=` (tasks·projects·reports) | `?org=` |
| 스키마 `TeamBrief` · `TeamOut` | `OrgBrief` · `OrgOut` (새 `TeamOut`은 **팀**을 뜻한다) |
| `MeOut.teams` | `MeOut.orgs` |
| `ProjectOut.team_id` · `ProjectCreateIn.team_id` | `org_id` (+ `ProjectOut.teams`) |
| `.env.discord` `TEAM_ID` | `ORG_ID` |
| MCP 도구 `list_teams` | `list_orgs` |
| 화면 문구 "팀 현황" · "팀원 관리" | "조직" · "멤버 관리" |

화면에 보이는 한국어는 조직을 "조직", 새 팀을 "팀"이라고 부른다.

---

## 2. Step 1. 앱 개명과 마이그레이션 초기화

운영 데이터가 없다. 마이그레이션을 처음부터 다시 쓴다.

```bash
cd core
git mv teams orgs
rm -f accounts/migrations/0*.py orgs/migrations/0*.py projects/migrations/0*.py tasks/migrations/0*.py api/migrations/0*.py
rm -f db.sqlite3
```

`orgs/apps.py`:

```python
from django.apps import AppConfig


class OrgsConfig(AppConfig):
    name = "orgs"
```

`config/settings.py`의 `INSTALLED_APPS`에서 `"teams"` → `"orgs"`. 순서는 `accounts`, `orgs`, `projects`, `tasks`, `reports`, `api`, `web`.

Step 2~7을 마친 뒤에 만든다.

```bash
uv run python manage.py makemigrations accounts orgs projects tasks api
uv run python manage.py migrate
```

`accounts` 마이그레이션은 `0002_discord_link`가 사라지고 `0001_initial` 하나가 된다. `discord_user_id`를 비우던 그 마이그레이션은 데이터 이전용이었으므로 초기화하면 필요 없다.

---

## 3. Step 2. `orgs/models.py` (전체)

```python
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _token():
    return secrets.token_urlsafe(32)


def _default_expiry():
    return timezone.now() + timedelta(days=7)


class Organization(models.Model):
    """가시성의 경계. 조직 멤버는 조직의 프로젝트·태스크를 전부 본다."""

    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="OrgMembership", related_name="orgs"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrgMembership(models.Model):
    ROLES = [("admin", "관리자"), ("member", "멤버")]

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships"
    )
    role = models.CharField(max_length=6, choices=ROLES, default="member")
    # 스킬 태그(부하 현황에서 담당자 찾기에 쓴다). ArrayField는 Postgres 전용이라
    # SQLite 테스트가 깨진다.
    tags = models.JSONField(default=list, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["org", "user"], name="orgmembership_org_user"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.org} ({self.role})"


class Team(models.Model):
    """조직 안의 사람 묶음(백엔드·프론트엔드 등).

    가시성을 제한하지 않는다. 부하 현황 필터, 프로젝트 담당 표시, GitHub 팀 연결에 쓴다.
    한 사람이 여러 팀에 속할 수 있다.
    """

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="TeamMembership", related_name="teams"
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["org", "name"], name="team_org_name"),
        ]

    def __str__(self):
        return f"{self.name} ({self.org.name})"


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="teammembership_team_user"),
        ]


class Invite(models.Model):
    """조직 초대 링크. 팀 배정은 하지 않는다(가입 후 팀 화면에서 넣는다)."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, default=_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    revoked_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    @property
    def path(self) -> str:
        return f"/join/{self.token}"
```

`orgs/admin.py`는 `Organization`·`OrgMembership`·`Team`·`TeamMembership`·`Invite`를 등록하도록 고친다.

`User.teams`의 뜻이 바뀐다는 것에 주의한다. 예전에는 조직이었고 이제는 팀이다. **`request.user.teams`를 쓰는 곳을 전부 `request.user.orgs`로 고친다**(`web/context.py`의 `team_count`가 그렇다).

---

## 4. Step 3. `orgs/services.py` (전체)

```python
from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import Invite, Organization, OrgMembership, Team, TeamMembership


# ---------- 조직 ----------


def orgs_of(user):
    """user가 속한 조직 queryset."""
    return Organization.objects.filter(memberships__user=user).distinct()


def is_member(user, org) -> bool:
    return OrgMembership.objects.filter(org=org, user=user).exists()


def is_admin(user, org) -> bool:
    return OrgMembership.objects.filter(org=org, user=user, role="admin").exists()


def require_admin(user, org):
    if not is_admin(user, org):
        raise ServiceError({"org": "조직 관리자만 할 수 있습니다."})


@transaction.atomic
def create_org(name: str, purpose: str, actor) -> Organization:
    name = name.strip()
    if not name:
        raise ServiceError({"name": "조직 이름을 입력하세요."})
    org = Organization.objects.create(
        name=name[:100], purpose=purpose.strip()[:200], created_by=actor
    )
    OrgMembership.objects.create(org=org, user=actor, role="admin")
    return org


def create_invite(org, actor, days: int = 7) -> Invite:
    require_admin(actor, org)
    if not 1 <= days <= 90:
        raise ServiceError({"days": "만료일은 1~90일 사이여야 합니다."})
    expires_at = timezone.now() + timezone.timedelta(days=days)
    return Invite.objects.create(org=org, created_by=actor, expires_at=expires_at)


def revoke_invite(invite, actor):
    require_admin(actor, invite.org)
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])


@transaction.atomic
def join_by_token(user, token: str) -> Organization:
    invite = Invite.objects.select_for_update().select_related("org").filter(token=token).first()
    if invite is None or not invite.is_usable:
        raise ServiceError({"token": "초대 링크가 유효하지 않거나 만료되었습니다."})
    _, created = OrgMembership.objects.get_or_create(
        org=invite.org, user=user, defaults={"role": "member"}
    )
    if created:
        invite.use_count += 1
        invite.save(update_fields=["use_count"])
    return invite.org


def change_role(membership, role: str, actor):
    require_admin(actor, membership.org)
    if role not in dict(OrgMembership.ROLES):
        raise ServiceError({"role": "알 수 없는 역할입니다."})
    if membership.role == "admin" and role != "admin" and _admin_count(membership.org) <= 1:
        raise ServiceError({"role": "마지막 관리자의 역할은 바꿀 수 없습니다."})
    membership.role = role
    membership.save(update_fields=["role"])


def set_tags(membership, tags, actor):
    """스킬 태그. 관리자만 고친다. 공백 제거·중복 제거·20자·최대 10개."""
    require_admin(actor, membership.org)
    cleaned, seen = [], set()
    for t in tags:
        t = (t or "").strip()[:20]
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    membership.tags = cleaned[:10]
    membership.save(update_fields=["tags"])


@transaction.atomic
def remove_member(membership, actor):
    """조직에서 빼면 그 조직의 모든 팀에서도 빠진다.

    TeamMembership은 조직이 아니라 팀을 가리키므로 cascade가 닿지 않는다. 여기서 지우지
    않으면 조직에 없는 사람이 팀 화면에 남는다.
    """
    require_admin(actor, membership.org)
    if membership.role == "admin" and _admin_count(membership.org) <= 1:
        raise ServiceError({"member": "마지막 관리자는 제거할 수 없습니다."})
    TeamMembership.objects.filter(team__org=membership.org, user=membership.user).delete()
    membership.delete()


def _admin_count(org) -> int:
    return OrgMembership.objects.filter(org=org, role="admin").count()


# ---------- 팀 ----------


def _validate_team_name(org, name: str, exclude_pk=None) -> str:
    name = (name or "").strip()
    if not name:
        raise ServiceError({"name": "팀 이름을 입력하세요."})
    name = name[:100]
    qs = Team.objects.filter(org=org, name=name)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ServiceError({"name": "같은 이름의 팀이 이미 있습니다."})
    return name


def create_team(*, org, name: str, purpose: str = "", actor) -> Team:
    require_admin(actor, org)
    return Team.objects.create(
        org=org,
        name=_validate_team_name(org, name),
        purpose=(purpose or "").strip()[:200],
        created_by=actor,
    )


def update_team(team, *, name: str, purpose: str = "", actor) -> Team:
    require_admin(actor, team.org)
    team.name = _validate_team_name(team.org, name, exclude_pk=team.pk)
    team.purpose = (purpose or "").strip()[:200]
    team.save(update_fields=["name", "purpose"])
    return team


def delete_team(team, actor):
    """팀만 지운다. 멤버는 조직에 그대로 남고 프로젝트도 지워지지 않는다."""
    require_admin(actor, team.org)
    team.delete()


def add_team_member(team, user, actor) -> TeamMembership:
    require_admin(actor, team.org)
    if not is_member(user, team.org):
        raise ServiceError({"user": "먼저 조직에 초대해야 합니다."})
    if not user.is_active:
        raise ServiceError({"user": "비활성 사용자는 팀에 넣을 수 없습니다."})
    membership, _ = TeamMembership.objects.get_or_create(team=team, user=user)
    return membership


def remove_team_member(team, user, actor):
    require_admin(actor, team.org)
    TeamMembership.objects.filter(team=team, user=user).delete()


def teams_of(user, org):
    """org 안에서 user가 속한 팀 queryset. 가시성 계산에 쓰지 않는다."""
    return Team.objects.filter(org=org, memberships__user=user).distinct()
```

---

## 5. Step 4. 다른 앱의 모델 변경

### `projects/models.py`

```python
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="projects")
    teams = models.ManyToManyField(
        "orgs.Team", blank=True, related_name="projects", verbose_name="담당 팀"
    )
```

`team` 필드를 지우고 위 둘을 넣는다. `Meta.constraints`의 unique는 `fields=["org", "name"]`, 이름은 `project_org_name`.

### `tasks/models.py`

`Task`는 바뀌지 않는다. 두 곳만 고친다.

```python
class Link(models.Model):
    KINDS = [
        ("doc", "문서"),
        ("issue", "이슈"),
        ("dash", "대시보드"),
        ("other", "기타"),
        # 아래 둘은 이제 폼에서 고를 수 없다. PR·저장소는 GitHub 연결이 자동으로 붙인다.
        ("pr", "PR"),
        ("repo", "저장소"),
    ]
```

```python
class ChangeLog(models.Model):
    SOURCES = [("web", "웹"), ("api", "API"), ("mcp", "AI"), ("dc", "Discord"), ("gh", "GitHub")]

    ...
    # GitHub 이벤트의 행위자가 아직 PM 계정과 이어지지 않았을 때 로그인을 남긴다(GUIDE-V2-07).
    # 그 사람이 GitHub를 연결하면 소급해서 actor를 채운다.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    external_actor = models.CharField(max_length=100, blank=True)
```

`ChangeLog.source`는 `max_length=4`다. `gh`는 들어간다. **늘리지 않는다.**
`Link.kind`는 `max_length=5`다. `issue`·`dash` 모두 들어간다. **늘리지 않는다.**

`external_actor`와 `actor`의 nullable은 `GUIDE-V2-07`까지 쓰이지 않는다. 마이그레이션을 두 번 만들지 않으려고 지금 넣는다.

### `tasks/admin.py` · `tasks/brief.py`

- `tasks/admin.py`: `list_filter`의 `"project__team"` → `"project__org"`. 안 바꾸면 admin 목록이 500이다.
- `tasks/brief.py`: `task_brief()`가 만드는 `project` dict의 `team_id` 키를 `org_id`로. 이 dict는 API(`ProjectBrief`)·Discord·MCP가 그대로 받는다.
- `api/schemas.py`의 `ProjectBrief.team_id` → `org_id` (7절의 `ProjectOut`과 별개다. 둘 다 바꾼다).

---

## 6. Step 5. services 고치기

### `projects/services.py`

- `from orgs.services import is_member, require_admin`
- `EDITABLE = {"name", "purpose", "owners", "status", "teams"}`
- `_validate(org, name, owners, status)` — owners가 그 **조직**의 활성 멤버인지 본다.
- `create_project(*, org, name, actor, ..., teams=())` — `project.teams.set(teams)`.
- `update_project` — `owners`와 같은 방식으로 `teams`를 다룬다. M2M이라 `update()` 밖에서 `set()`하고, 바뀌었으면 `_log(project, "teams", _ids(old), _ids(new), ...)`.
- `archive_project`·`restore_project`의 `require_admin(actor, project.org)`.
- `project_stats`는 그대로다.
- `teams`에 다른 조직의 팀이 들어오면 거부한다.

```python
    for t in teams:
        if t.org_id != org.pk:
            raise ServiceError({"teams": "다른 조직의 팀은 담당으로 지정할 수 없습니다."})
```

### `tasks/services.py`

- `from orgs.services import is_member, orgs_of`
- `_require_member(actor, project)` → `is_member(actor, project.org)`, 오류 키는 `"project"` 그대로.
- `visible_tasks(user)` → `Task.objects.filter(project__org__in=orgs_of(user)).select_related("project", "project__org", "assignee")`
- `today_items(user, day)` → `task__project__org__in=orgs_of(user)`
- `QuickTaskForm`이 쓰는 프로젝트 범위(`web/forms.py`)도 `team__in=teams_of(user)` → `org__in=orgs_of(user)`.
- 나머지(상태 전이·기한·체크리스트·오늘 목록·me_view·search)는 **규칙이 바뀌지 않는다.**

### `reports/services.py` — `org_status()`로 개명하고 확장

조직 개요·부하 현황·담당자별이 **이 함수 한 번의 호출**에서 나와야 한다.

```python
from collections import defaultdict

from django.db.models import Count, Q

from common.dates import today_kst, week_bounds
from orgs.models import Team, TeamMembership
from tasks.brief import user_brief
from tasks.models import Task


def _open_qs(org):
    return Task.objects.filter(
        project__org=org, project__is_archived=False, status__in=Task.OPEN
    )


def org_status(org) -> dict:
    """조직 지표. 키: counts, by_project, by_assignee, capacity, projects_without_owner"""
    today = today_kst()
    monday, sunday = week_bounds(today)
    open_qs = _open_qs(org)
    counts = {
        "open": open_qs.count(),
        "doing": open_qs.filter(status="doing").count(),
        "review": open_qs.filter(status="review").count(),
        "blocked": open_qs.filter(status="blocked").count(),
        "overdue": open_qs.filter(due_date__lt=today).count(),
        "due_this_week": open_qs.filter(due_date__gte=monday, due_date__lte=sunday).count(),
        "no_due": open_qs.filter(due_date__isnull=True).count(),
        "done": Task.objects.filter(
            project__org=org, project__is_archived=False, status="done"
        ).count(),
    }

    projects = (
        org.projects.filter(is_archived=False)
        .prefetch_related("owners", "teams")
        .annotate(
            open_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN)),
            overdue_count=Count(
                "tasks", filter=Q(tasks__status__in=Task.OPEN, tasks__due_date__lt=today)
            ),
            review_count=Count("tasks", filter=Q(tasks__status="review")),
            blocked_count=Count("tasks", filter=Q(tasks__status="blocked")),
            done_count=Count("tasks", filter=Q(tasks__status="done")),
            total_count=Count("tasks", filter=~Q(tasks__status="cancelled")),
        )
    )
    by_project = [
        {
            "id": p.pk,
            "name": p.name,
            "status": p.status,
            "owners": [user_brief(u) for u in p.owners.all()],
            "teams": [{"id": t.pk, "name": t.name} for t in p.teams.all()],
            "open": p.open_count,
            "overdue": p.overdue_count,
            "review": p.review_count,
            "blocked": p.blocked_count,
            "done": p.done_count,
            "total": p.total_count,
        }
        for p in projects
    ]

    by_assignee = list(
        open_qs.values("assignee_id", "assignee__display_name")
        .annotate(
            open=Count("id"),
            doing=Count("id", filter=Q(status="doing")),
            overdue=Count("id", filter=Q(due_date__lt=today)),
            review=Count("id", filter=Q(status="review")),
            blocked=Count("id", filter=Q(status="blocked")),
        )
        .order_by("-open")
    )

    # 부하 현황은 미완료가 하나도 없는 사람도 보여야 한다. by_assignee는 집계라
    # 태스크가 있는 사람만 나오므로 활성 멤버 전원을 기준으로 다시 만든다.
    rows = {r["assignee_id"]: r for r in by_assignee}
    tags_by_user = {m.user_id: m.tags for m in org.memberships.all()}
    teams_by_user = defaultdict(list)
    for tm in TeamMembership.objects.filter(team__org=org).select_related("team"):
        teams_by_user[tm.user_id].append({"id": tm.team_id, "name": tm.team.name})

    members = list(org.members.filter(is_active=True).order_by("display_name"))
    capacity = []
    for u in members:
        r = rows.get(u.pk, {})
        doing, review = r.get("doing", 0), r.get("review", 0)
        overdue = r.get("overdue", 0)
        capacity.append(
            {
                "user": user_brief(u),
                "open": r.get("open", 0),
                "doing": doing,
                "review": review,
                "blocked": r.get("blocked", 0),
                "overdue": overdue,
                "load": doing + review,
                "tags": tags_by_user.get(u.pk, []),
                "teams": teams_by_user.get(u.pk, []),
            }
        )
    max_load = max([c["load"] for c in capacity], default=0) or 1
    for c in capacity:
        c["bar"] = round(c["load"] / max_load * 100)
        c["over"] = c["load"] >= 4 or c["overdue"] >= 2
        c["verdict"] = "과부하" if c["over"] else "여유" if c["load"] <= 1 else "적정"
    counts["avg_doing"] = round(sum(c["doing"] for c in capacity) / len(members), 1) if members else 0.0

    projects_without_owner = list(
        org.projects.filter(is_archived=False, owners__isnull=True).values("id", "name")
    )
    return {
        "counts": counts,
        "by_project": by_project,
        "by_assignee": by_assignee,
        "capacity": capacity,
        "projects_without_owner": projects_without_owner,
    }
```

`weekly()`는 인자 이름과 필터만 `org`로 바꾼다. 반환 키(`team`)는 `org`로 바꾸고 `discord_service`의 `summarize`·`messages`에서 읽는 곳을 함께 고친다.

---

## 7. Step 6. API

| 파일 | 변경 |
|---|---|
| `api/context.py` | `team_or_404` → `org_or_404`(`Organization` 조회, `orgs.services.is_member`) |
| `api/routers/teams.py` → `api/routers/orgs.py` | 경로 `/{org_id}`, `/{org_id}/members`, `/{org_id}/status`, `/{org_id}/invites`, `/invites/{id}`. **추가**: `GET /{org_id}/teams` |
| `api/routers/tasks.py` | 쿼리 `team` → `org`, 필터 `project__org_id` |
| `api/routers/projects.py` | 쿼리 `team` → `org`. `ProjectCreateIn.org_id`, `team_ids` 추가 |
| `api/routers/reports.py` | 쿼리 `team` → `org` |
| `api/api.py` | `api.add_router("/orgs", orgs.router)` |
| `api/schemas.py` | 아래 |
| `api/serialize.py` | `project_out`에 `org_id`·`teams` |

```python
class OrgBrief(Schema):
    id: int
    name: str
    purpose: str
    role: str


class TeamOut(Schema):       # 새 의미: 조직 안의 사람 묶음
    id: int
    name: str
    purpose: str
    member_count: int


class MeOut(Schema):
    ...
    orgs: list[OrgBrief]


class OrgOut(Schema):        # 기존 TeamOut
    id: int
    name: str
    purpose: str
    role: str
    projects: list[ProjectOut]
    teams: list[TeamOut]
```

`ProjectOut`은 `team_id` → `org_id`, `teams: list[TeamOut]` 추가. `ProjectCreateIn`·`ProjectPatchIn`은 `team_id` → `org_id`, `team_ids: list[int]`.

---

## 8. Step 7. web

이 단계에서는 **이름만 바꾼다.** 화면 구조는 `GUIDE-V2-02`에서 바꾼다.

| 파일 | 변경 |
|---|---|
| `web/views/common.py` | `team_or_404` → `org_or_404`, `current_team` → `current_org`(세션 키 `org_id`), `project_or_404`는 `select_related("org")` |
| `web/views/teams.py` → `web/views/orgs.py` | 함수 `team_current`→`org_current`, `team_list`→`org_list`, `team_new`→`org_new`, `team_detail`→`org_detail`, `members`는 그대로. `team_status(team)` → `org_status(org)` |
| `web/views/projects.py` | `project.team` → `project.org`, `team_or_404` → `org_or_404` |
| `web/views/tasks.py`·`today.py`·`me.py`·`search.py` | `teams_of` → `orgs_of`, `project.team` → `project.org` |
| `web/views/auth.py` | `from teams.services import join_by_token` → `orgs.services`, `request.session["team_id"]` → `org_id`, 가입 안내 문구 "{team.name} 팀에 참여" → "{org.name} 조직에 참여" |
| `web/views/ops.py` | 내보내기 모델 목록 `Team`·`Membership`·`Invite` → `Organization`·`OrgMembership`·`Invite`·`Team`·`TeamMembership`. `Invite`의 `fields=("team", …)` → `("org", …)` |
| `web/views/common.py` | `project_or_404`의 `is_member(user, p.team)` → `p.org` (select_related도 `"org"`). `me_view` 제목 "팀 전체 태스크" → "조직 전체 태스크" (`tasks/services.py`), `me.html`의 select 옵션 "팀 전체" → "조직 전체" |
| `README.md`(루트) | 표의 `TEAM_ID` → `ORG_ID`, "팀 현황" 문구 → "조직". 디자인 핸드오프 절 안의 문구는 목업 인용이므로 두되, 절 첫머리에 "여기의 팀은 개명 전 용어로 조직을 뜻한다" 한 줄을 넣는다 |
| `web/context.py` | `current_org`, `nav_projects = org.projects...`, `team_count` → `org_count = request.user.orgs.count()`, `NAV_BY_URL`의 값 `"team"` → `"org"`와 새 URL 이름 |
| `web/forms.py` | `TeamForm` → `OrgForm`, `ProjectForm(team=)` → `(org=)`, `TaskForm`·`TaskInlineForm`의 `team` 인자 → `org`, `QuickTaskForm`의 프로젝트 범위 |
| `web/urls.py` | 대조표대로 |
| `templates/teams/` → `templates/orgs/` | `detail.html`·`list.html`·`new.html`·`members.html`. 문구 "팀 현황"→"조직", "내 팀"→"내 조직", "팀 만들기"→"조직 만들기", "팀원 관리"→"멤버 관리" |
| `templates/base.html` | 내비 라벨 "팀 현황" → "조직", `{% url 'team' %}` → `{% url 'org' %}`, `team_count` → `org_count` |
| `templates/projects/detail.html` | `project.team_id` → `project.org_id`, 상단 링크 문구 |
| `templates/auth/join.html` | "팀" → "조직" |

`tasks/detail.html`·`_panel.html`·`_row.html`은 프로젝트만 참조하므로 바뀌지 않는다.

`tasks/services.py`의 오류 문구 "이 팀의 멤버가 아닙니다."는 "이 조직의 멤버가 아닙니다."로 바꾼다. 오류 키(`project`)는 그대로다. 이 문자열을 검사하는 테스트가 있으면 함께 고친다.

---

## 9. Step 8. 다른 파트

### `discord_service`

- `config.py`: `team_id` → `org_id`, 환경 변수 `TEAM_ID` → `ORG_ID`.
- `scheduler.py`: `cfg.team_id` 세 곳 → `cfg.org_id`.
- `core_client.py`: `open_tasks(org_id, ...)`의 params `"team"` → `"org"`, `weekly(org_id, week_start)`의 params `"team"` → `"org"`.
- `notify.py`·`weekly.py`·`__main__.py`: 인자 이름.
- `summarize.py`·`messages.py`: 주간 집계의 `data["team"]` → `data["org"]`.
- `README.md`와 `.env.discord.example`의 표.
- 테스트의 픽스처 이름.

### `mcp_server`

- `server.py`: 도구 `list_teams` → `list_orgs`(설명도 "조직"으로), `GET /api/me` 응답의 `teams` → `orgs`.
- `list_tasks`·`list_projects`·`get_weekly_report_data`의 `team` 인자 → `org`. `get_team_status` → `get_org_status`, `list_members`의 `team_id` 인자 → `org_id`, 경로 `/api/teams/{id}/…` → `/api/orgs/{id}/…`.
- 도구 개수는 14개 그대로다. **새 도구를 만들지 않는다.**
- `tests/test_tools.py`의 이름 집합.

---

## 10. Step 9. 테스트

`core/conftest.py`의 `team` 픽스처를 `org`로 개명하고, **새 의미의 `team` 픽스처를 추가**한다.

```python
@pytest.fixture
def org(admin, member):
    o = create_org("산돌이", "학생 챗봇 서비스", admin)
    OrgMembership.objects.create(org=o, user=member, role="member")
    return o


@pytest.fixture
def team(org, admin, member):
    t = create_team(org=org, name="백엔드", actor=admin)
    add_team_member(t, member, admin)
    return t


@pytest.fixture
def project(org, admin):
    return create_project(org=org, name="학식 API", actor=admin, owners=[admin], status="active")
```

기존 테스트에서 `team` 인자를 쓰던 곳을 전부 `org`로 바꾼다. `teams/tests.py`는 `orgs/tests.py`가 된다.

새로 추가할 테스트:

| 이름 | 확인하는 것 |
|---|---|
| `test_team_member_must_be_org_member` | 조직 밖 사용자를 팀에 넣으면 `ServiceError` |
| `test_user_in_multiple_teams` | 한 사람이 두 팀에 속하고 `teams_of(user, org)`가 둘 다 돌려준다 |
| `test_team_name_unique_per_org` | 같은 조직에 같은 팀 이름이 두 번 안 된다. 다른 조직에는 된다 |
| `test_remove_org_member_clears_team_memberships` | 조직에서 빼면 그 조직의 팀에서도 빠진다 |
| `test_delete_team_keeps_members_and_projects` | 팀을 지워도 조직 멤버십과 프로젝트는 남는다 |
| `test_team_does_not_limit_visibility` | 어느 팀에도 속하지 않은 조직 멤버가 모든 프로젝트의 태스크를 본다 |
| `test_project_teams_must_be_same_org` | 다른 조직의 팀을 담당으로 넣으면 거부 |
| `test_project_teams_logged` | 담당 팀을 바꾸면 `ChangeLog`에 `teams` 행이 남는다 |
| `test_org_status_counts_and_capacity` | `counts`에 `doing`·`done`·`avg_doing`이 있고, 미완료가 없는 멤버도 `capacity`에 나온다 |
| `test_capacity_verdict_thresholds` | 부하 4 이상 또는 기한 초과 2 이상이면 과부하, 1 이하면 여유 |
| `test_set_tags_admin_only_and_cleans` | 관리자만, 중복·공백 제거, 10개 상한 |
| `test_team_endpoints_in_api` | `GET /api/orgs/{id}/teams`가 팀 목록을 돌려준다 |

---

## 11. 검증

```bash
cd core
uv run ruff format . && uv run ruff check .
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
DATABASE_URL=postgres://pm:pm@127.0.0.1:5432/pm uv run pytest -q
cd ../discord_service && uv run pytest -q && uv run ruff check .
cd ../mcp_server && uv run pytest -q && uv run ruff check .
```

남은 개명을 찾는다. 저장소 전체를 본다. **아래 두 명령의 결과가 `docs/GUIDE-01~04`·`docs/IMPL-PLAN.md`·`docs/PLAN.md`·목업 파일 밖에서는 비어야 한다.**

```bash
grep -rn -E "teams_of|team_status|current_team|team_or_404|TeamForm|TeamBrief|memberships__team|project__team|project\.team|\.team_id|team_id|from teams|import teams|['\"]team(_list|_detail|_new|_members)?['\"]|/teams/|user\.teams|TEAM_ID|list_teams|get_team_status" \
  --include=*.py --include=*.html --include=*.toml --include=*.example --include=*.md \
  core discord_service mcp_server README.md compose.yml .env.discord.example \
  | grep -v "/migrations/" | grep -v "docs/GUIDE-0" | grep -v "docs/IMPL-PLAN.md" | grep -v "docs/PLAN.md"

grep -rn -E "팀 현황|팀원 관리|내 팀|팀 만들기|팀에 참여|팀 전체|이 팀의" \
  core/web/templates core/web/views core/tasks core/orgs core/api discord_service/discord_service mcp_server/mcp_server
```

첫 명령은 영문 식별자, 둘째는 한국어 문구다. 둘째에서 새 의미의 팀("팀 만들기" 등 `GUIDE-V2-02`에서 만드는 문구)가 걸리면 그것은 정상이다. 이 단계에서는 아직 그 화면이 없으므로 비어야 한다.

화면 확인:

- 로그인 → `/today` → `/org` → `/orgs/<id>` → `/orgs/<id>/members` → `/projects/<id>` 가 전부 열린다.
- 초대 링크로 다른 계정이 조직에 들어온다.
- `/api/docs`가 열리고 `/api/orgs/{id}`, `/api/orgs/{id}/teams`가 있다.

## 12. 완료 체크

- [ ] `orgs` 앱에 모델 5개, 마이그레이션은 앱마다 `0001_initial` 하나
- [ ] 팀이 가시성을 자르지 않는다(테스트로 고정)
- [ ] 조직에서 빼면 팀에서도 빠진다
- [ ] `org_status()`가 `counts`·`by_project`·`by_assignee`·`capacity`를 한 번에 돌려준다
- [ ] 기존 테스트가 이름만 바뀐 채 전부 통과, 신규 12개 추가
- [ ] `discord_service`·`mcp_server`가 `ORG_ID`·`list_orgs`로 동작
- [ ] 11절의 `grep` 두 개가 저장소 전체에서 비어 있다(discord_service·mcp_server 포함)
