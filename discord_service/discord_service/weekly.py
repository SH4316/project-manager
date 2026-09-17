import json
import logging
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import Bot, UnknownResult
from .store import Store
from .summarize import summarize

log = logging.getLogger(__name__)


def last_monday(today: date) -> date:
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def run_weekly(
    core: CoreClient,
    bot: Bot,
    store: Store,
    org_id: int,
    week_start: date,
    provider: str,
    force: bool = False,
    *,
    enabled: bool = True,
    channel_id: str | None = None,
) -> dict:
    """`enabled=False`(조직 설정 `notify.weekly_enabled` off)면 만들지도 보내지도 않는다.

    # ponytail: `notify.team_channel_weekly`(팀 채널에도 게시)는 이번 라운드에 넣지 않는다.
    # 팀별로 담당 프로젝트를 추려 보내려면 channels_post.py급의 새 집계가 필요하고, 조직
    # 채널 게시만으로도 지금 요구는 채운다. 필요해지면 이 함수에 team_channel_ids=[] 를
    # 받아 같은 summary를 그 채널들에도 `bot.send_channel`하는 한 줄로 끝난다.
    """
    ws = week_start.isoformat()
    if not enabled:
        return {"status": "disabled", "period_start": ws}
    if not force and store.weekly_sent(org_id, ws):
        return {"status": "skipped", "period_start": ws}
    data = core.weekly(org_id, ws)
    summary, source = summarize(data, provider)
    try:
        bot.send_channel(summary, channel_id)
        status = "sent"
    except UnknownResult:
        status = "unknown"
    except Exception as e:  # noqa: BLE001
        log.error("주간 보고 발송 실패: %s", e)
        status = "failed"
    store.save_weekly(org_id, ws, json.dumps(data, ensure_ascii=False), summary, source, status)
    return {"status": status, "period_start": ws, "source": source}
