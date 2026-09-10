from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Schema
from pydantic import Field

Status = Literal["todo", "doing", "paused", "blocked", "review", "done", "cancelled"]
Priority = Annotated[int, Field(ge=1, le=10)]
ProjectStatus = Literal[
    "preparing", "on_hold", "waiting", "active", "paused", "done", "stopped", "eol"
]


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


# ---------- Discord 봇 ----------
# discord_user_id는 게이트웨이가 채운 author.id다. 클라이언트가 고르는 값이 아니다.


class DiscordLinkIn(Schema):
    code: str
    discord_user_id: str


class DiscordActorIn(Schema):
    discord_user_id: str


class DiscordExtendIn(Schema):
    discord_user_id: str
    due_date: date
    reason: str = ""


class ErrorOut(Schema):
    detail: dict | str


class ConflictOut(Schema):
    detail: str
    latest: dict
