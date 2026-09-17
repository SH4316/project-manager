def test_claim_is_exclusive(store):
    assert store.claim(1, "d3", "2026-09-12") is True
    assert store.claim(1, "d3", "2026-09-12") is False


def test_release_only_sending(store):
    store.claim(1, "d3", "2026-09-12")
    store.mark(1, "d3", "2026-09-12", "sent")
    store.release(1, "d3", "2026-09-12")
    assert len(store.recent()["sent"]) == 1


def test_claim_daily(store):
    assert store.claim_daily(1, "overdue", "2026-09-09") is True
    assert store.claim_daily(1, "overdue", "2026-09-09") is False
    store.release_daily(1, "overdue", "2026-09-09")
    assert store.claim_daily(1, "overdue", "2026-09-09") is True


def test_claim_daily_is_scoped_per_org(store):
    """다중 조직(§8.4): 조직마다 자리가 따로다 — 한 조직의 발송이 다른 조직을 막지 않는다."""
    assert store.claim_daily(1, "deadline", "2026-09-09") is True
    assert store.claim_daily(2, "deadline", "2026-09-09") is True
    assert store.claim_daily(1, "deadline", "2026-09-09") is False


def test_weekly_scoped_per_org(store):
    assert store.weekly_sent(1, "2026-08-31") is False
    store.save_weekly(1, "2026-08-31", "{}", "요약", "fixed", "sent")
    assert store.weekly_sent(1, "2026-08-31") is True
    assert store.weekly_sent(2, "2026-08-31") is False  # 다른 조직은 섞이지 않는다


def test_seen_status_roundtrip(store):
    assert store.seen_status(1, 5) is None
    store.mark_seen(1, 5, "todo")
    assert store.seen_status(1, 5) == "todo"
    store.mark_seen(1, 5, "done")
    assert store.seen_status(1, 5) == "done"
    assert store.seen_status(2, 5) is None  # 다른 조직은 별개다


def test_migration_keeps_old_single_org_rows(tmp_path):
    """옛 파일(daily·weekly에 org_id가 없다)을 열어도 깨지지 않고 org_id=0으로 읽힌다."""
    import sqlite3

    path = str(tmp_path / "old.sqlite")
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE daily(kind TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY(kind, date));"
        "CREATE TABLE weekly(period_start TEXT PRIMARY KEY, data_json TEXT NOT NULL, "
        "summary TEXT NOT NULL, source TEXT NOT NULL, sent_status TEXT NOT NULL, sent_at TEXT);"
    )
    conn.execute("INSERT INTO daily(kind, date) VALUES('deadline', '2026-09-01')")
    conn.execute(
        "INSERT INTO weekly(period_start, data_json, summary, source, sent_status, sent_at) "
        "VALUES('2026-08-24', '{}', 's', 'fixed', 'sent', '2026-08-31')"
    )
    conn.commit()
    conn.close()

    from discord_service.store import Store

    s = Store(path)
    assert s.claim_daily(0, "deadline", "2026-09-01") is False  # 옛 행은 org_id=0으로 살아 있다
    assert s.claim_daily(1, "deadline", "2026-09-01") is True  # 새 조직은 별개 자리다
    assert s.weekly_sent(0, "2026-08-24") is True


def test_dm_channel_cache_roundtrip(store):
    """DM 채널 캐시는 넣고 읽고 지우는 것뿐이다. 없으면 None."""
    assert store.dm_channel("111") is None
    store.save_dm_channel("111", "dm-111")
    assert store.dm_channel("111") == "dm-111"
    store.save_dm_channel("111", "dm-222")  # 같은 사람은 덮어쓴다
    assert store.dm_channel("111") == "dm-222"
    store.forget_dm_channel("111")
    assert store.dm_channel("111") is None
