import argparse
import json
import logging
from datetime import date, datetime

from . import listener
from .config import Config
from .core_client import CoreClient
from .discord import Bot
from .messages import test_message
from .notify import run_deadlines
from .scheduler import loop, tick
from .store import Store
from .weekly import last_monday, run_weekly


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="discord_service")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="60초 루프로 상주 (발송)")
    sub.add_parser("bot", help="DM 명령 수신으로 상주 (게이트웨이)")
    sub.add_parser("once", help="지금 시각 기준 tick 1회")
    sub.add_parser("test", help="조직 채널에 테스트 메시지 1건")
    w = sub.add_parser("weekly", help="주간 보고")
    w.add_argument("--now", action="store_true", help="이미 보냈어도 다시 보낸다")
    w.add_argument("--week-start", help="YYYY-MM-DD (월요일)")
    d = sub.add_parser("deadlines", help="마감 알림 즉시 실행")
    d.add_argument("--date", help="YYYY-MM-DD 기준일 (기본 오늘)")
    sub.add_parser("status", help="최근 발송 기록")
    a = p.parse_args()

    cfg = Config.from_env()
    core = CoreClient(cfg.core_url, cfg.core_token)

    # 상주 명령은 Store·Bot을 여기서 만들지 않는다. 리스너는 SQLite를 아예 열지 않고,
    # loop()는 자기 것을 만든다(같은 파일을 두 번 열지 않는다).
    if a.cmd == "bot":
        listener.run(cfg, core)
        return
    if a.cmd == "run":
        loop(cfg)
        return

    store = Store(cfg.db_path)
    bot = Bot(cfg.bot_token, cfg.channel_id, store)

    if a.cmd == "once":
        print(tick(cfg, core, bot, store, datetime.now(cfg.tz)))
    elif a.cmd == "test":
        bot.send_channel(test_message(cfg.site_name))
        print("sent")
    elif a.cmd == "weekly":
        ws = (
            date.fromisoformat(a.week_start)
            if a.week_start
            else last_monday(datetime.now(cfg.tz).date())
        )
        print(run_weekly(core, bot, store, cfg.org_id, ws, cfg.llm_provider, force=a.now))
    elif a.cmd == "deadlines":
        today = date.fromisoformat(a.date) if a.date else datetime.now(cfg.tz).date()
        print(run_deadlines(core, bot, store, cfg.org_id, today))
    elif a.cmd == "status":
        print(json.dumps(store.recent(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
