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
