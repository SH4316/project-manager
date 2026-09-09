import json
import logging
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import UnknownResult, Webhook
from .store import Store
from .summarize import summarize

log = logging.getLogger(__name__)


def last_monday(today: date) -> date:
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def run_weekly(
    core: CoreClient,
    hook: Webhook,
    store: Store,
    team_id: int,
    week_start: date,
    provider: str,
    force: bool = False,
) -> dict:
    ws = week_start.isoformat()
    if not force and store.weekly_sent(ws):
        return {"status": "skipped", "period_start": ws}
    data = core.weekly(team_id, ws)
    summary, source = summarize(data, provider)
    try:
        hook.send(summary)
        status = "sent"
    except UnknownResult:
        status = "unknown"
    except Exception as e:  # noqa: BLE001
        log.error("주간 보고 발송 실패: %s", e)
        status = "failed"
    store.save_weekly(ws, json.dumps(data, ensure_ascii=False), summary, source, status)
    return {"status": status, "period_start": ws, "source": source}
