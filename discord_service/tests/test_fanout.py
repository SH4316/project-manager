"""발송 대상은 core(웹 화면의 팀 → 알림 채널)에서 읽는다. 환경 변수는 예비용."""

import httpx
import pytest
from conftest import FakeCore, FakeHook, make_core

from discord_service.discord import Fanout

A = "https://discord.com/api/webhooks/1/aaa"
B = "https://discord.com/api/webhooks/2/bbb"
ENV = "https://discord.com/api/webhooks/9/env"


def make_fanout(core_fake, fake_hook, fallback="", ttl=60):
    return Fanout(
        make_core(core_fake),
        team_id=1,
        fallback_url=fallback,
        ttl=ttl,
        transport=httpx.MockTransport(fake_hook.handler),
        sleep=lambda s: None,
    )


def test_sends_to_every_registered_channel():
    fake_hook = FakeHook()
    core = FakeCore([], webhook_urls=[A, B])
    make_fanout(core, fake_hook).send("안녕")
    assert fake_hook.urls == [A, B]
    assert fake_hook.sent == ["안녕", "안녕"]


def test_channel_list_is_cached_for_ttl():
    fake_hook = FakeHook()
    core = FakeCore([], webhook_urls=[A])
    f = make_fanout(core, fake_hook)
    f.send("1")
    f.send("2")
    assert core.webhook_calls == 1  # 메시지마다 다시 묻지 않는다


def test_keeps_last_list_when_core_goes_down():
    fake_hook = FakeHook()
    core = FakeCore([], webhook_urls=[A])
    f = make_fanout(core, fake_hook, ttl=0)
    f.send("1")
    core.webhook_status = 500
    f.send("2")  # 마지막으로 읽은 목록으로 계속 보낸다
    assert fake_hook.urls == [A, A]


def test_falls_back_to_env_url_when_core_never_answers():
    fake_hook = FakeHook()
    core = FakeCore([], webhook_urls=[])
    core.webhook_status = 500
    make_fanout(core, fake_hook, fallback=ENV).send("안녕")
    assert fake_hook.urls == [ENV]


def test_no_channel_no_send():
    """등록도 없고 예비 주소도 없으면 조용히 넘기지 않고 실패로 남긴다."""
    fake_hook = FakeHook()
    core = FakeCore([], webhook_urls=[])
    with pytest.raises(RuntimeError, match="알림 채널"):
        make_fanout(core, fake_hook).send("안녕")
    assert fake_hook.sent == []


def test_turning_every_channel_off_stops_sending():
    """관리자가 채널을 전부 끄면 알림도 멈춘다. 보이지 않는 예비 주소로 새지 않는다."""
    fake_hook = FakeHook()
    core = FakeCore([], webhook_urls=[])
    with pytest.raises(RuntimeError, match="알림 채널"):
        make_fanout(core, fake_hook, fallback=ENV).send("안녕")
    assert fake_hook.urls == []


def test_config_error_from_core_is_not_papered_over():
    """4xx(토큰·권한·팀)는 설정 문제다. 예비 주소로 조용히 보내지 않고 실패시킨다."""
    fake_hook = FakeHook()
    core = FakeCore([], webhook_urls=[A])
    core.webhook_status = 403
    with pytest.raises(httpx.HTTPStatusError):
        make_fanout(core, fake_hook, fallback=ENV).send("안녕")
    assert fake_hook.urls == []


def test_one_dead_channel_does_not_block_the_others():
    """한 채널이 죽어도 나머지에는 간다. 그 알림 자체는 실패로 남는다."""
    fake_hook = FakeHook(statuses=[500, 500, 500])  # A만 3회 실패, B는 기본 204
    core = FakeCore([], webhook_urls=[A, B])
    with pytest.raises(RuntimeError, match="3회 실패"):
        make_fanout(core, fake_hook).send("안녕")
    assert fake_hook.urls == [A, A, A, B]


def test_send_failure_is_reported_to_core_as_not_ok(store, tmp_path):
    """등록된 채널이 없어 전부 실패하면 /ops에 ok로 보이지 않아야 한다."""
    from datetime import date, datetime, timedelta, timezone

    from conftest import task

    from discord_service.config import Config
    from discord_service.scheduler import tick

    kst = timezone(timedelta(hours=9))
    today = date(2026, 9, 9)
    core_fake = FakeCore([task(1, today.isoformat())], webhook_urls=[])
    core = make_core(core_fake)
    fanout = make_fanout(core_fake, FakeHook())  # 채널 0개, 예비 주소 없음
    cfg = Config(
        core_url="http://core",
        core_token="pm_x",
        team_id=1,
        webhook_url="",
        tz=kst,
        send_hour=9,
        weekly_weekday=6,
        weekly_hour=9,
        llm_provider="",
        db_path=str(tmp_path / "s.sqlite"),
        site_name="산돌이 업무",
    )
    r = tick(cfg, core, fanout, store, datetime(2026, 9, 9, 10, tzinfo=kst))
    assert r and r[0]["failed"] == 1
    assert core_fake.status_reports[-1]["ok"] is False
