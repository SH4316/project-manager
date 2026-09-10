"""봇에게 온 DM을 받는 상주 프로세스.

`import discord`는 절대 임포트라 site-packages의 discord.py를 가리킨다
(같은 패키지의 `discord_service/discord.py`가 아니다 — 패키지 디렉터리는 sys.path에 없다).

인텐트는 `DIRECT_MESSAGES`(1<<12) 하나, 비특권이다. 봇에게 온 DM의 본문은
MESSAGE_CONTENT 특권 인텐트 없이도 전달된다(문서 명시 예외). 특권 인텐트는 켜지 않는다.
"""

import asyncio
import logging
import time

import discord

from .commands import handle
from .core_client import CoreClient
from .discord import chunk

log = logging.getLogger(__name__)

# 발신자별 분당 한도. core의 처리량 제한(60/m)은 봇 계정 하나로 세므로 한 사람이
# 다 쓰면 다른 사람 명령까지 429가 된다.
RATE = 20


def too_fast(seen: dict[str, list[float]], uid: str, now: float) -> bool:
    recent = [t for t in seen.get(uid, []) if now - t < 60]
    recent.append(now)
    seen[uid] = recent
    return len(recent) > RATE


def run(cfg, core: CoreClient):
    intents = discord.Intents.none()
    intents.dm_messages = True
    client = discord.Client(intents=intents)
    seen: dict[str, list[float]] = {}

    @client.event
    async def on_ready():
        log.info("discord 봇 접속: %s", client.user)

    @client.event
    async def on_message(message):
        if message.author.bot or message.guild is not None:
            return  # 자기 메시지 루프 방지 + DM만 받는다
        uid = str(message.author.id)
        if too_fast(seen, uid, time.monotonic()):
            log.warning("발신자 한도 초과로 무시: %s", uid)
            return
        # CoreClient는 동기 httpx다. 이벤트 루프에서 그대로 부르면 하트비트가 굶어
        # 게이트웨이가 연결을 끊는다.
        reply = await asyncio.to_thread(handle, core, uid, message.content)
        for part in chunk(reply):
            await message.channel.send(part, allowed_mentions=discord.AllowedMentions.none())

    # 재접속·하트비트·RESUME·close code 처리는 라이브러리가 맡는다.
    client.run(cfg.bot_token, log_handler=None)
