from ninja.errors import HttpError
from ninja.security import HttpBearer

from accounts.models import ApiToken

WRITE_EXEMPT_PREFIX = "/api/integrations/"


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
