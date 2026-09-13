"""봇에게 온 DM과 슬래시 명령을 받는 상주 프로세스.

`import discord`는 절대 임포트라 site-packages의 discord.py를 가리킨다
(같은 패키지의 `discord_service/discord.py`가 아니다 — 패키지 디렉터리는 sys.path에 없다).

인텐트는 `DIRECT_MESSAGES`(1<<12)와 `GUILDS`(1<<0) 둘, 모두 비특권이다. 봇에게 온 DM의 본문은
MESSAGE_CONTENT 특권 인텐트 없이도 전달된다(문서 명시 예외). 길드 인텐트는 채널을 만들 길드
캐시 때문이다. 특권 인텐트는 켜지 않는다. 슬래시 명령(인터랙션)도 게이트웨이로 온다 —
공개 엔드포인트도 서명 검증도 없다.
"""

import asyncio
import logging
import time

import discord
from discord import app_commands

from .commands import RATE, handle, too_fast  # noqa: F401  (RATE·too_fast는 기존 import 경로 유지)
from .core_client import CoreClient
from .discord import chunk
from .slash import register

log = logging.getLogger(__name__)


def run(cfg, core: CoreClient):
    intents = discord.Intents.none()
    intents.dm_messages = True
    intents.guilds = True
    client = discord.Client(intents=intents)
    seen: dict[str, list[float]] = {}

    tree = app_commands.CommandTree(client)
    guild = discord.Object(id=int(cfg.guild_id)) if cfg.guild_id else None
    if guild is not None:
        register(tree, guild, cfg, core, seen)
    else:
        log.warning("DISCORD_GUILD_ID 가 없어 슬래시 명령을 등록하지 않습니다 (DM 명령만 동작)")

    async def setup_hook():
        # 길드 범위 동기화는 즉시 반영된다(전역은 최대 1시간). on_ready는 재접속마다 다시
        # 불리므로 거기서 하면 매번 API를 때린다.
        if guild is not None:
            await tree.sync(guild=guild)

    client.setup_hook = setup_hook

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
