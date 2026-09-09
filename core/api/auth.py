from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from accounts.models import ApiToken

WRITE_EXEMPT_PREFIX = "/api/integrations/"


class BrowserSessionAuth(SessionAuth):
    """세션 쿠키가 실제로 있을 때만 동작한다.

    django-ninja의 SessionAuth는 쿠키를 읽기 전에 CSRF를 검사하고 실패하면 403을 던진다.
    인증 목록의 첫 번째라서, 쿠키가 없는 Bearer 요청(MCP·Discord)까지 403이 되어 버린다.
    쿠키가 없으면 곧바로 넘겨 TokenAuth가 처리하게 한다. 쿠키가 있으면 CSRF 검사는 그대로다.
    """

    def __call__(self, request):
        if self.param_name not in request.COOKIES:
            return None
        return super().__call__(request)


class TokenAuth(HttpBearer):
    def authenticate(self, request, token):
        t = ApiToken.authenticate(token)
        if t is None:
            return None
        if (
            t.scope == "read"
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and not request.path.startswith(WRITE_EXEMPT_PREFIX)
        ):
            raise HttpError(403, "읽기 전용 토큰입니다.")
        request.api_token = t
        return t.user
