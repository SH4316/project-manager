import logging
import re

_PATTERNS = [
    re.compile(r"pm_[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)bearer\s+\S+"),
    # Discord 봇 토큰은 `Authorization: Bot <token>`으로 실린다. bearer 패턴이 못 잡는다.
    re.compile(r"(?i)\bbot\s+[A-Za-z0-9_\-.]{20,}"),
    re.compile(r"[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{27,}"),
    re.compile(r"(?i)DISCORD_BOT_TOKEN=\S+"),
    re.compile(r"/u/[A-Za-z0-9_\-]{20,}/"),
]


class SecretFilter(logging.Filter):
    """로그 메시지에서 API 토큰과 Discord 봇 토큰을 가린다."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in _PATTERNS:
            msg = p.sub("[redacted]", msg)
        record.msg = msg
        record.args = ()
        return True
