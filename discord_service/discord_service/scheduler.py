import logging
import time
from datetime import datetime

from .config import Config
from .core_client import CoreClient
from .discord import Bot
from .notify import run_deadlines
from .store import Store
from .weekly import last_monday, run_weekly

log = logging.getLogger(__name__)

# 놓아준 자리를 다시 훑을 기회. 하루 1회 문턱을 무한히 열어 주면 core가 아픈 동안 매 분
# 전체 스캔을 반복해 처리량 제한(60/m)을 스스로 태운다.
RETRY_SWEEPS = 3


def _reopen_today(store: Store, day: str) -> bool:
    """놓아준 알림이 있을 때 그날 문턱을 다시 연다. 하루 RETRY_SWEEPS번까지.

    중복 발송 걱정은 없다 — 이미 보낸 묶음은 `sent` 행이 막는다. 다시 여는 것은
    '아직 안 보낸 묶음만' 다시 훑겠다는 뜻이다.
    """
    for n in range(1, RETRY_SWEEPS + 1):
        if store.claim_daily(f"deadline-retry-{n}", day):
            store.release_daily("deadline", day)
            return True
    return False


def tick(cfg: Config, core: CoreClient, bot: Bot, store: Store, now: datetime) -> list[dict]:
    """1분마다 호출. 실행한 작업 결과 목록."""
    results = []
    today = now.date()
    day = today.isoformat()
    if now.hour >= cfg.send_hour and store.claim_daily("deadline", day):
        try:
            r = run_deadlines(core, bot, store, cfg.team_id, today)
            # 발송 실패는 예외로 올라오지 않고 결과에 세어진다(DM 거부·채널 열기 실패·재확인 실패).
            # /ops에 ok로 보이면 아무도 모른다. 미연결(unlinked)은 실패가 아니다 —
            # 한 명이 연결을 안 했다고 /ops가 영구 빨강이 되면 그 신호를 아무도 안 본다.
            retry_later = r["open_failed"] + r["recheck_failed"]
            ok = r["failed"] == 0 and retry_later == 0
            # 놓아준 자리는 그날 문턱을 다시 열어야 실제로 재시도된다. release()만으로는
            # claim_daily가 이미 소비돼 그날 다시 안 돈다(= 그 사람은 알림을 못 받는다).
            if retry_later:
                r["reopened"] = _reopen_today(store, day)
            store.record_run("deadline", ok, str(r))
            core.report_status(ok, {"job": "deadline", **r})
            results.append({"job": "deadline", **r})
        except Exception as e:  # noqa: BLE001
            store.release_daily("deadline", day)  # 다음 tick에 다시 시도
            store.record_run("deadline", False, str(e))
            core.report_status(False, {"job": "deadline", "error": str(e)})
            log.exception("deadline job failed")
    if now.weekday() == cfg.weekly_weekday and now.hour >= cfg.weekly_hour:
        ws = last_monday(today)
        if not store.weekly_sent(ws.isoformat()):
            try:
                r = run_weekly(core, bot, store, cfg.team_id, ws, cfg.llm_provider)
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
    store = Store(cfg.db_path)
    bot = Bot(cfg.bot_token, cfg.channel_id, store)
    log.info("discord_service 시작 (team=%s, send_hour=%s)", cfg.team_id, cfg.send_hour)
    while True:
        try:
            tick(cfg, core, bot, store, datetime.now(cfg.tz))
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        time.sleep(60)
