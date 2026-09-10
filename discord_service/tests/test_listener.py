"""발신자별 쿨다운. core의 처리량 제한은 봇 계정 하나로 세므로 한 사람이 다 쓰면 안 된다."""

from discord_service.listener import RATE, too_fast


def test_rate_limit_per_sender():
    seen = {}
    assert all(too_fast(seen, "111", 100.0) is False for _ in range(RATE))
    assert too_fast(seen, "111", 100.0) is True  # 21번째
    assert too_fast(seen, "222", 100.0) is False  # 다른 사람은 영향 없다


def test_window_resets_after_60s():
    seen = {}
    for _ in range(RATE + 1):
        too_fast(seen, "111", 100.0)
    assert too_fast(seen, "111", 161.0) is False
    assert len(seen["111"]) == 1  # 지난 창은 버린다
