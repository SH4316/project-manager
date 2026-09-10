"""봇 REST 발송. 개인 DM과 팀 채널 두 경로만 있다."""

import httpx
import pytest
from conftest import CHANNEL, FakeBot, make_bot

from discord_service.discord import (
    MAX_LEN,
    Bot,
    ChannelOpenFailed,
    DmBlocked,
    chunk,
)


def test_chunk_splits_long_text():
    text = "".join(f"{i:03d} " + "가" * 30 + "\n" for i in range(100))
    assert len(text) > 3000
    parts = chunk(text)
    assert len(parts) >= 2
    assert all(len(p) <= MAX_LEN for p in parts)
    assert "".join(parts) == text


def test_dm_opens_channel_then_sends_with_bot_headers():
    """DM 1건 = 채널 개설 1회 + 발송 1회. 멘션은 만들지 않는다."""
    fake = FakeBot()
    make_bot(fake).send_dm("111", "안녕")
    assert [c["path"] for c in fake.calls] == [
        "/users/@me/channels",
        "/channels/dm-111/messages",
    ]
    assert fake.opened == ["111"]
    assert fake.messages[0]["allowed_mentions"] == {"parse": []}
    assert "<@" not in fake.messages[0]["content"]
    assert all(c["auth"] == "Bot botsecret" for c in fake.calls)
    # UA가 없으면 Cloudflare가 40333으로 막는다.
    assert all(c["ua"].startswith("DiscordBot (") for c in fake.calls)


def test_channel_post_allows_user_mentions():
    """팀 채널 게시는 멘션이 목적이다. @everyone은 여전히 못 만든다."""
    fake = FakeBot()
    make_bot(fake).send_channel("@everyone <@111> 안녕")
    assert fake.messages[0]["channel"] == CHANNEL
    assert fake.messages[0]["allowed_mentions"] == {"parse": ["users"]}


def test_dm_channel_is_cached(store):
    """같은 사람에게 두 번 보내도 채널은 한 번만 연다(40003 방지)."""
    fake = FakeBot()
    bot = make_bot(fake, store)
    bot.send_dm("111", "하나")
    bot.send_dm("111", "둘")
    assert fake.opened == ["111"]
    assert fake.dm("111") == ["하나", "둘"]


def test_unknown_channel_reopens_once(store):
    """10003이면 캐시를 지우고 딱 한 번 다시 연다."""
    fake = FakeBot(errors={"dm-111": [(404, {"code": 10003})]})
    store.save_dm_channel("111", "dm-111")
    assert make_bot(fake, store).send_dm("111", "안녕") == "sent"
    assert fake.opened == ["111"]  # 죽은 캐시를 지우고 1회만 다시 연다
    assert fake.attempts("dm-111") == 2
    assert fake.dm("111") == ["안녕"]


def test_blocked_dm_raises_without_retry(store):
    """50007은 그 사람에게 영구적이다. 재시도가 invalid-request 예산만 태운다."""
    fake = FakeBot(errors={"dm-111": [(403, {"code": 50007})]})
    with pytest.raises(DmBlocked) as e:
        make_bot(fake, store).send_dm("111", "안녕")
    assert e.value.code == 50007
    assert fake.attempts("dm-111") == 1
    assert fake.messages == []


def test_retries_429_with_retry_after(store):
    fake = FakeBot(errors={"*": [429]})
    assert make_bot(fake, store).send_dm("111", "안녕") == "sent"
    assert fake.attempts("dm-111") == 2
    assert fake.dm("111") == ["안녕"]


def test_reopen_resends_only_the_failing_chunk(store):
    """조각 여러 개 중 하나에서 채널이 죽으면 그 조각부터 이어 보낸다.

    본문 전체를 다시 보내면 앞 조각이 두 번 도착한다.
    """
    text = "".join(f"{i:03d} " + "가" * 30 + chr(10) for i in range(100))
    parts = chunk(text)
    assert len(parts) >= 2
    # 첫 조각은 성공, 두 번째에서 캐시한 채널이 죽는다.
    fake = FakeBot(errors={"dm-111": [200, (404, {"code": 10003})]})
    store.save_dm_channel("111", "dm-111")
    assert make_bot(fake, store).send_dm("111", text) == "sent"
    assert fake.dm("111") == parts  # 각 조각이 정확히 한 번씩


def test_channel_open_failure_is_retryable_not_unknown(store):
    """채널 열기 실패는 '보냈는지 모름'이 아니다 — 아직 아무것도 보내지 않았다."""

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    bot = Bot(
        "botsecret", CHANNEL, store, transport=httpx.MockTransport(down), sleep=lambda s: None
    )
    with pytest.raises(ChannelOpenFailed):
        bot.send_dm("111", "안녕")
    assert store.dm_channel("111") is None
