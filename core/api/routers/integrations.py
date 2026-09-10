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
