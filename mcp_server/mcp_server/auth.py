import re
from contextvars import ContextVar

current_token: ContextVar[str | None] = ContextVar("current_token", default=None)

_PATH_RE = re.compile(r"^/u/([A-Za-z0-9_\-]{20,})(/.*)?$")


def extract_from_scope(scope) -> tuple[str | None, str]:
    """ASGI scope에서 (토큰, 새 경로)를 얻는다.
    1) /u/<token>/mcp 형태면 토큰을 꺼내고 경로를 /mcp 로 바꾼다.
    2) 아니면 Authorization: Bearer 헤더를 본다.
    """
    path = scope.get("path", "")
    m = _PATH_RE.match(path)
    if m:
        return m.group(1), m.group(2) or "/"
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), path
    return None, path


class TokenMiddleware:
    """토큰을 contextvar에 넣고, /u/<token>/... 경로를 /... 로 바꿔 넘긴다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token, new_path = extract_from_scope(scope)
        scope = dict(scope)
        scope["path"] = new_path
        scope["raw_path"] = new_path.encode()
        reset = current_token.set(token)
        try:
            return await self.app(scope, receive, send)
        finally:
            current_token.reset(reset)


def require_token() -> str:
    t = current_token.get()
    if not t:
        raise PermissionError(
            "인증 토큰이 없습니다. Authorization 헤더 또는 개인 비밀 URL을 사용하세요."
        )
    return t


# ponytail: URL 토큰은 프록시 로그에 남을 수 있다. 커넥터 UX가 필요해지면 OAuth 2.1 + 동적 클라이언트 등록으로 교체.
