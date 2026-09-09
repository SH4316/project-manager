import logging
import re

_PATTERNS = [
    re.compile(r"pm_[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"/u/[A-Za-z0-9_\-]{20,}/"),
    re.compile(r"https://discord\.com/api/webhooks/\S+"),
]


class SecretFilter(logging.Filter):
    """로그 메시지에서 토큰·Webhook URL을 가린다."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in _PATTERNS:
            msg = p.sub("[redacted]", msg)
        record.msg = msg
        record.args = ()
        return True
