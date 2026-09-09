from datetime import date

from conftest import FakeCore, FakeHook, make_core, make_hook, task, weekly_data

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


def test_run_weekly_once_per_period(store, fake_hook, hook):
    core = make_core(FakeCore([], weekly=weekly_data(completed=[task(1, "2026-09-02")])))
    assert run_weekly(core, hook, store, 1, WS, "")["status"] == "sent"
    assert run_weekly(core, hook, store, 1, WS, "")["status"] == "skipped"
    assert run_weekly(core, hook, store, 1, WS, "", force=True)["status"] == "sent"


def test_run_weekly_marks_failed_but_saves(store):
    fake = FakeHook(statuses=[500, 500, 500])
    core = make_core(FakeCore([], weekly=weekly_data(completed=[task(1, "2026-09-02")])))
    r = run_weekly(core, make_hook(fake), store, 1, WS, "")
    assert r["status"] == "failed"
    assert store.recent()["weekly"][0]["sent_status"] == "failed"


def test_last_monday():
    assert last_monday(date(2026, 9, 9)) == date(2026, 8, 31)
