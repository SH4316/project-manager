"""Discord 봇 명령이 들어오는 곳.

봇은 자기 이름으로 일하지 않는다. 연결된 Discord 사용자를 **사람**으로 바꿔 그 사람의 팀
범위 안에서만 움직인다(`get_visible_task(actor, …)`). 변경 이력에는 행위자=그 사람,
경로=Discord(`dc`), 토큰=봇 토큰이 남는다.

라우터 인증이 `BotTokenAuth` 하나라서 세션 쿠키·읽기·쓰기 토큰은 이 경로에 들어오지 못한다.
"""

from ninja import Router
from ninja.errors import HttpError

from accounts.services import link_discord, unlink_discord_by_id, user_by_discord_id
from tasks.brief import task_brief
from tasks.services import extend_due, get_visible_task, today_view, transition

from ..auth import BotTokenAuth
from ..schemas import DiscordActorIn, DiscordExtendIn, DiscordLinkIn
from ..serialize import task_out

router = Router(tags=["discord"], auth=BotTokenAuth())

UNLINKED = "연결되지 않은 Discord 계정입니다. 웹 설정 → 프로필에서 연결 코드를 받으세요."


def _actor(discord_user_id: str):
    user = user_by_discord_id(discord_user_id)
    if user is None:
        raise HttpError(404, UNLINKED)
    return user


def _ctx(request, actor) -> dict:
    """X-Source 헤더를 믿지 않는다. 이 라우터에 들어온 것 자체가 경로의 증거다."""
    return {"actor": actor, "source": "dc", "token": getattr(request, "api_token", None)}


def _task(actor, task_id: int):
    task = get_visible_task(actor, task_id)
    if task is None:
        raise HttpError(404, "태스크를 찾을 수 없습니다.")
    return task


@router.post("/link", response=dict)
def link(request, payload: DiscordLinkIn):
    user = link_discord(payload.code, payload.discord_user_id)
    return {"display_name": user.display_name}


@router.post("/unlink", response=dict)
def unlink(request, payload: DiscordActorIn):
    return {"unlinked": unlink_discord_by_id(payload.discord_user_id)}


@router.post("/today", response=dict)
def today(request, payload: DiscordActorIn):
    """식별자를 쿼리 문자열에 싣지 않으려고 GET이 아니라 POST다."""
    actor = _actor(payload.discord_user_id)
    view = today_view(actor)
    return {
        "display_name": actor.display_name,
        "date": view["date"].isoformat(),
        "items": [task_brief(t) for t in view["items"]],
        "counts": view["counts"],
    }


@router.post("/tasks/{task_id}/done", response=dict)
def done(request, task_id: int, payload: DiscordActorIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    was = task.get_status_display()
    # 사용자는 버전을 본 적이 없다. 의도는 "지금 완료로 바꿔라"다. 한 요청 안에서 읽고
    # 그 값으로 CAS를 건다 — 그 사이(수 ms)에 끼면 409로 알린다(조용히 덮어쓰지 않는다).
    task = transition(
        task, "done", expected_version=task.version, reason="", **_ctx(request, actor)
    )
    return {"was": was, "task": task_out(task)}


@router.post("/tasks/{task_id}/extend", response=dict)
def extend(request, task_id: int, payload: DiscordExtendIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    task = extend_due(
        task,
        payload.due_date,
        payload.reason,
        expected_version=task.version,
        **_ctx(request, actor),
    )
    return {"task": task_out(task)}
