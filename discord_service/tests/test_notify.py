from datetime import date, timedelta, timezone

from conftest import FakeCore, FakeHook, make_core, make_hook, task

from discord_service.config import Config
from discord_service.notify import classify, run_deadlines
from discord_service.scheduler import tick

TODAY = date(2026, 9, 9)
# tzdata가 없는 환경(Windows)에서도 돌도록 고정 오프셋을 쓴다. 운영은 ZoneInfo("Asia/Seoul").
KST = timezone(timedelta(hours=9))


def _cfg(tmp_path):
    return Config(
        core_url="http://core",
        core_token="pm_test",
        team_id=1,
        webhook_url="https://discord.com/api/webhooks/x/y",
        tz=KST,
        send_hour=9,
        weekly_weekday=0,
        weekly_hour=9,
        llm_provider="",
        db_path=str(tmp_path / "s.sqlite"),
        site_name="산돌이 업무",
    )


def test_classify():
    assert classify(task(1, "2026-09-12"), TODAY) == "d3"
    assert classify(task(1, "2026-09-10"), TODAY) == "d1"
    assert classify(task(1, "2026-09-09"), TODAY) == "d0"
    assert classify(task(1, "2026-09-01"), TODAY) == "overdue"
    assert classify(task(1, "2026-09-11"), TODAY) is None
    assert classify(task(1, None), TODAY) is None
    assert classify(task(1, "2026-09-09", status="done"), TODAY) is None


def test_sends_each_kind_once(store, fake_hook, hook):
    core = make_core(
        FakeCore(
            [
                task(1, "2026-09-12"),
                task(2, "2026-09-10"),
                task(3, "2026-09-09"),
                task(4, "2026-09-01"),
                task(5, "2026-09-02"),
            ]
        )
    )
    r = run_deadlines(core, hook, store, 1, TODAY)
    assert r["sent"] == 4
    assert len(fake_hook.sent) == 4
    overdue_msg = [m for m in fake_hook.sent if "기한 초과" in m][0]
    assert "TASK-4" in overdue_msg and "TASK-5" in overdue_msg

    r2 = run_deadlines(core, hook, store, 1, TODAY)
    assert r2["sent"] == 0
    assert r2["skipped"] >= 4


def test_due_changed_before_send_not_sent(store, fake_hook, hook, monkeypatch):
    fake = FakeCore([task(1, "2026-09-12")])
    core = make_core(fake)
    monkeypatch.setattr(type(core), "task", lambda self, tid: task(tid, "2026-09-20"), raising=True)
    r = run_deadlines(core, hook, store, 1, TODAY)
    assert r["sent"] == 0
    assert r["skipped"] == 1
    assert store.recent()["sent"] == []


def test_completed_before_send_not_sent(store, fake_hook, hook, monkeypatch):
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    monkeypatch.setattr(
        type(core), "task", lambda self, tid: task(tid, "2026-09-12", status="done"), raising=True
    )
    assert run_deadlines(core, hook, store, 1, TODAY)["sent"] == 0


def test_blocked_task_included(store, fake_hook, hook):
    core = make_core(
        FakeCore(
            [
                task(1, "2026-09-09", status="blocked", stop_reason="서류 대기"),
                task(2, "2026-09-10", status="paused"),
            ]
        )
    )
    r = run_deadlines(core, hook, store, 1, TODAY)
    assert r["sent"] == 2
    joined = "\n".join(fake_hook.sent)
    assert "막힘" in joined
    assert "서류 대기" in joined
    assert "일시정지" in joined


def test_no_backfill_for_missed_days(store, fake_hook, hook):
    core = make_core(FakeCore([task(1, "2026-09-11")]))
    r = run_deadlines(core, hook, store, 1, TODAY)
    assert r["sent"] == 0
    assert fake_hook.sent == []


def test_failed_send_recorded(store):
    fake = FakeHook(statuses=[500, 500, 500])
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    r = run_deadlines(core, make_hook(fake), store, 1, TODAY)
    assert r["failed"] == 1
    assert store.recent()["sent"][0]["status"] == "failed"


def test_retry_on_429_then_success(store):
    fake = FakeHook(statuses=[429, 204])
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    r = run_deadlines(core, make_hook(fake), store, 1, TODAY)
    assert r["sent"] == 1
    assert len(fake.sent) == 2


def test_status_reported_to_core(tmp_path, fake_hook, hook, store):
    from datetime import datetime

    fake = FakeCore([task(1, "2026-09-12")])
    core = make_core(fake)
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 9, 10, 0, tzinfo=cfg.tz)
    tick(cfg, core, hook, store, now)
    assert fake.status_reports[-1]["ok"] is True
