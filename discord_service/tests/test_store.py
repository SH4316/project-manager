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
