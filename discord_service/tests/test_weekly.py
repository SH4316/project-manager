from datetime import date

from conftest import CHANNEL, FakeCore, make_bot, make_core, member, task, weekly_data

from discord_service.summarize import fixed_summary, summarize
from discord_service.weekly import last_monday, run_weekly

WS = date(2026, 8, 31)


def test_fixed_summary_quiet():
    data = weekly_data()
    assert "특이 사항 없음" in fixed_summary(data)


def test_fixed_summary_sections():
    data = weekly_data(completed=[task(1, "2026-09-02")], overdue=[task(2, "2026-09-01")])
    text = fixed_summary(data)
    assert "지난주 완료" in text
    assert "기한 초과" in text
    assert "TASK-1" in text and "TASK-2" in text
    assert "<@111>" in text


def test_summarize_falls_back_when_provider_fails():
    _, source = summarize(weekly_data(), "bogus")
    assert source == "fixed"


def test_run_weekly_goes_to_the_team_channel(store, fake_bot, bot):
    """주간 보고는 팀 채널에 게시한다(멘션이 목적이라 users만 허용)."""
    data = weekly_data(
        completed=[task(1, "2026-09-02")],
        members=[member(), member(4, "", "미연결")],
    )
    core = make_core(FakeCore([], weekly=data))
    assert run_weekly(core, bot, store, 1, WS, "")["status"] == "sent"
    assert [m["channel"] for m in fake_bot.messages] == [CHANNEL]
    assert fake_bot.messages[0]["allowed_mentions"] == {"parse": ["users"]}
    # /ops는 staff만 보지만 이 보고는 당사자가 본다.
    assert "⚠️ Discord 미연결: 미연결" in fake_bot.messages[0]["content"]


def test_run_weekly_once_per_period(store, fake_bot, bot):
    core = make_core(FakeCore([], weekly=weekly_data(completed=[task(1, "2026-09-02")])))
    assert run_weekly(core, bot, store, 1, WS, "")["status"] == "sent"
    assert run_weekly(core, bot, store, 1, WS, "")["status"] == "skipped"
    assert run_weekly(core, bot, store, 1, WS, "", force=True)["status"] == "sent"
    assert len(fake_bot.messages) == 2


def test_run_weekly_marks_failed_but_saves(store):
    from conftest import FakeBot

    fake = FakeBot(errors={"*": [500, 500, 500]})
    core = make_core(FakeCore([], weekly=weekly_data(completed=[task(1, "2026-09-02")])))
    r = run_weekly(core, make_bot(fake, store), store, 1, WS, "")
    assert r["status"] == "failed"
    assert store.recent()["weekly"][0]["sent_status"] == "failed"


def test_last_monday():
    assert last_monday(date(2026, 9, 9)) == date(2026, 8, 31)
