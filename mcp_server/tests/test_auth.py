import pytest

from mcp_server.auth import TokenMiddleware, current_token, extract_from_scope, require_token

TOKEN = "pm_abcdefghijklmnopqrstuvwxyz"


def test_extract_from_path():
    token, path = extract_from_scope({"path": f"/u/{TOKEN}/mcp", "headers": []})
    assert token == TOKEN
    assert path == "/mcp"


def test_extract_from_header():
    token, path = extract_from_scope(
        {"path": "/mcp", "headers": [(b"authorization", f"Bearer {TOKEN}".encode())]}
    )
    assert token == TOKEN
    assert path == "/mcp"


def test_no_token():
    assert extract_from_scope({"path": "/mcp", "headers": []}) == (None, "/mcp")


def test_require_token_raises():
    tok = current_token.set(None)
    try:
        with pytest.raises(PermissionError):
            require_token()
    finally:
        current_token.reset(tok)


async def test_middleware_rewrites_path_and_sets_token():
    seen = {}

    async def inner(scope, receive, send):
        seen["path"] = scope["path"]
        seen["token"] = current_token.get()

    app = TokenMiddleware(inner)
    await app(
        {"type": "http", "path": f"/u/{TOKEN}/mcp", "headers": []},
        None,
        None,
    )
    assert seen["path"] == "/mcp"
    assert seen["token"] == TOKEN
    assert current_token.get() is None
