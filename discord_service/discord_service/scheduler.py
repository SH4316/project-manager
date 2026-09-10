import logging
import time
from datetime import datetime

from .config import Config
from .core_client import CoreClient
from .discord import Fanout, Sender
from .notify import run_deadlines
from .store import Store
from .weekly import last_monday, run_weekly

log = logging.getLogger(__name__)


def tick(cfg: Config, core: CoreClient, hook: Sender, store: Store, now: datetime) -> list[dict]:
    """1분마다 호출. 실행한 작업 결과 목록."""
    results = []
    today = now.date()
    if now.hour >= cfg.send_hour and store.claim_daily("deadline", today.isoformat()):
        try:
            r = run_deadlines(core, hook, store, cfg.team_id, today)
            # 발송 실패는 예외로 올라오지 않고 결과에 세어진다(채널 하나가 죽었거나
            # 등록된 채널이 아예 없을 때). /ops에 ok로 보이면 아무도 모른다.
            ok = r["failed"] == 0
            store.record_run("deadline", ok, str(r))
            core.report_status(ok, {"job": "deadline", **r})
            results.append({"job": "deadline", **r})
        except Exception as e:  # noqa: BLE001
            store.release_daily("deadline", today.isoformat())  # 다음 tick에 다시 시도
            store.record_run("deadline", False, str(e))
            core.report_status(False, {"job": "deadline", "error": str(e)})
            log.exception("deadline job failed")
    if now.weekday() == cfg.weekly_weekday and now.hour >= cfg.weekly_hour:
        ws = last_monday(today)
        if not store.weekly_sent(ws.isoformat()):
            try:
                r = run_weekly(core, hook, store, cfg.team_id, ws, cfg.llm_provider)
                store.record_run("weekly", r["status"] == "sent", str(r))
                core.report_status(r["status"] == "sent", {"job": "weekly", **r})
                results.append({"job": "weekly", **r})
            except Exception as e:  # noqa: BLE001
                store.record_run("weekly", False, str(e))
                core.report_status(False, {"job": "weekly", "error": str(e)})
                log.exception("weekly job failed")
    return results


def loop(cfg: Config):
    # ponytail: 단일 프로세스 전제. 복제 수를 늘리면 SQLite 파일을 공유하지 못하므로 1개만 띄운다.
    core = CoreClient(cfg.core_url, cfg.core_token)
    hook = Fanout(core, cfg.team_id, cfg.webhook_url)
    store = Store(cfg.db_path)
    log.info("discord_service 시작 (team=%s, send_hour=%s)", cfg.team_id, cfg.send_hour)
    while True:
        try:
            tick(cfg, core, hook, store, datetime.now(cfg.tz))
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        time.sleep(60)
