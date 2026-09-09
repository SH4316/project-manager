import time

import httpx

MAX_LEN = 1900  # Discord content 한도 2000자, 여유


def chunk(text: str) -> list[str]:
    """줄 단위로 1900자 이하 조각으로 나눈다."""
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > MAX_LEN and buf:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts or [""]


class UnknownResult(Exception):
    """응답을 못 받아 성공 여부를 모른다."""


class Webhook:
    def __init__(self, url: str, transport=None, sleep=time.sleep):
        self.url = url
        self.http = httpx.Client(timeout=15, transport=transport)
        self.sleep = sleep

    def send(self, text: str) -> str:
        """'sent' | 'unknown' 를 돌려주거나, 3회 실패 시 예외를 던진다."""
        for part in chunk(text):
            self._send_one(part)
        return "sent"

    def _send_one(self, content: str):
        delay = 2.0
        last = None
        for _ in range(3):
            try:
                r = self.http.post(
                    self.url,
                    json={"content": content, "allowed_mentions": {"parse": ["users"]}},
                )
            except httpx.TimeoutException as e:
                raise UnknownResult(str(e)) from e
            except httpx.HTTPError as e:
                last = e
                self.sleep(delay)
                delay *= 2
                continue
            if r.status_code in (200, 204):
                return
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = float(r.headers.get("Retry-After", delay))
                last = RuntimeError(f"HTTP {r.status_code}")
                self.sleep(max(retry_after, delay))
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise RuntimeError(f"3회 실패: {last}")
