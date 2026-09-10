import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    core_url: str
    core_token: str
    team_id: int
    bot_token: str
    channel_id: str
    tz: ZoneInfo
    send_hour: int
    weekly_weekday: int
    weekly_hour: int
    llm_provider: str
    db_path: str
    site_name: str

    @classmethod
    def from_env(cls) -> "Config":
        def need(k):
            v = os.environ.get(k, "").strip()
            if not v:
                raise SystemExit(f"환경 변수 {k} 가 필요합니다.")
            return v

        return cls(
            core_url=need("CORE_URL").rstrip("/"),
            core_token=need("CORE_TOKEN"),
            team_id=int(need("TEAM_ID")),
            bot_token=need("DISCORD_BOT_TOKEN"),
            channel_id=need("DISCORD_CHANNEL_ID"),
            tz=ZoneInfo(os.environ.get("TZ", "Asia/Seoul")),
            send_hour=int(os.environ.get("SEND_HOUR", "9")),
            weekly_weekday=int(os.environ.get("WEEKLY_WEEKDAY", "0")),
            weekly_hour=int(os.environ.get("WEEKLY_HOUR", "9")),
            llm_provider=os.environ.get("LLM_PROVIDER", "").strip().lower(),
            db_path=os.environ.get("DB_PATH", "/data/discord.sqlite"),
            site_name=os.environ.get("SITE_NAME", "산돌이 업무"),
        )
