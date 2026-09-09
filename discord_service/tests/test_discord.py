from conftest import FakeHook, make_hook

from discord_service.discord import MAX_LEN, chunk


def test_chunk_splits_long_text():
    text = "".join(f"{i:03d} " + "가" * 30 + "\n" for i in range(100))
    assert len(text) > 3000
    parts = chunk(text)
    assert len(parts) >= 2
    assert all(len(p) <= MAX_LEN for p in parts)
    assert "".join(parts) == text


def test_no_everyone_mentions():
    fake = FakeHook()
    make_hook(fake).send("@everyone 안녕")
    assert fake.payloads[0]["allowed_mentions"] == {"parse": ["users"]}
