from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from teams.services import active_webhook_urls, is_admin

from ..context import team_or_404
from ..models import IntegrationStatus
from ..schemas import StatusIn

router = Router(tags=["integrations"])
ALLOWED = {"discord", "mcp"}


@router.get("/discord/webhooks", response=dict)
def discord_webhooks(request, team: int):
    """discord 서비스가 발송 대상 주소를 읽어 가는 곳.

    Webhook 주소는 그 자체가 비밀이라 팀 관리자만 볼 수 있다. 연동 계정을 그 팀의
    관리자로 넣어야 한다(읽기 토큰이면 이 팀의 다른 것은 바꿀 수 없다).
    """
    t = team_or_404(request, team)
    if not is_admin(request.auth, t):
        raise HttpError(403, "팀 관리자만 볼 수 있습니다.")
    return {"urls": active_webhook_urls(t)}


@router.post("/{name}/status", response={204: None})
def report_status(request, name: str, payload: StatusIn):
    if name not in ALLOWED:
        raise HttpError(404, "알 수 없는 통합 이름입니다.")
    IntegrationStatus.objects.update_or_create(
        name=name,
        defaults={"last_run_at": timezone.now(), "ok": payload.ok, "detail": payload.detail},
    )
    return 204, None
