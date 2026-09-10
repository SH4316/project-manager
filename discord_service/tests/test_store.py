def test_claim_is_exclusive(store):
    assert store.claim(1, "d3", "2026-09-12") is True
    assert store.claim(1, "d3", "2026-09-12") is False


def test_release_only_sending(store):
    store.claim(1, "d3", "2026-09-12")
    store.mark(1, "d3", "2026-09-12", "sent")
    store.release(1, "d3", "2026-09-12")
    assert len(store.recent()["sent"]) == 1


def test_claim_daily(store):
    assert store.claim_daily("overdue", "2026-09-09") is True
    assert store.claim_daily("overdue", "2026-09-09") is False
    store.release_daily("overdue", "2026-09-09")
    assert store.claim_daily("overdue", "2026-09-09") is True


def test_dm_channel_cache_roundtrip(store):
    """DM 채널 캐시는 넣고 읽고 지우는 것뿐이다. 없으면 None."""
    assert store.dm_channel("111") is None
    store.save_dm_channel("111", "dm-111")
    assert store.dm_channel("111") == "dm-111"
    store.save_dm_channel("111", "dm-222")  # 같은 사람은 덮어쓴다
    assert store.dm_channel("111") == "dm-222"
    store.forget_dm_channel("111")
    assert store.dm_channel("111") is None
