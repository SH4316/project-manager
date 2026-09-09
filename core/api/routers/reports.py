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
