import logging
import time

import httpx

log = logging.getLogger(__name__)

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


class Fanout:
    """core에 등록된 팀 채널 전부로 보낸다.

    주소는 웹 화면에서 관리하므로 여기서 60초 캐시해 두고, core가 **일시적으로** 안 되면
    마지막으로 읽은 목록(없으면 환경 변수 `DISCORD_WEBHOOK_URL`)을 쓴다.
    core가 4xx로 답하면(토큰·권한·팀) 설정 문제라 그대로 실패시킨다.
    `Webhook.send`와 같은 모양이라 notify·weekly는 그대로 쓴다.

    여러 채널 중 한 곳이 실패해도 나머지 채널에는 보낸다. 그 뒤 첫 예외를 다시 던져
    그 알림을 실패로 남긴다(store가 자리를 잡아 두었으니 다음 실행에서 중복 발송되지 않는다).
    """

    def __init__(self, core, team_id: int, fallback_url: str = "", ttl: int = 60, **hook_kwargs):
        self.core = core
        self.team_id = team_id
        self.fallback_url = fallback_url
        self.ttl = ttl
        self.hook_kwargs = hook_kwargs
        self._urls: list[str] | None = None
        self._read_at = 0.0
        # 상주 프로세스다. 메시지마다 httpx.Client를 새로 만들면 소켓이 쌓인다.
        self._hooks: dict[str, Webhook] = {}

    def targets(self) -> list[str]:
        now = time.monotonic()
        if self._urls is None or now - self._read_at > self.ttl:
            try:
                self._urls = self.core.webhook_urls(self.team_id)
                self._read_at = now
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    # 토큰·권한·팀 설정 문제다. 예비 주소로 조용히 흘려보내면
                    # 관리자가 화면에서 끈 채널로 계속 알림이 나갈 수 있다.
                    raise
                log.warning("core가 알림 채널 목록을 주지 못했다: %s", e)
            except Exception as e:  # noqa: BLE001  일시적 장애가 알림을 영구히 막지 않게
                log.warning("core에서 알림 채널 목록을 읽지 못했다: %s", e)
        if self._urls is not None:
            return self._urls  # 빈 목록은 "보낼 곳 없음"이 맞다. 예비 주소로 넘기지 않는다
        return [self.fallback_url] if self.fallback_url else []

    def send(self, text: str) -> str:
        urls = self.targets()
        if not urls:
            raise RuntimeError("보낼 알림 채널이 없습니다. 웹에서 팀 → 알림 채널에 등록하세요.")
        first = None
        for url in urls:
            try:
                self._hooks.setdefault(url, Webhook(url, **self.hook_kwargs)).send(text)
            except Exception as e:  # noqa: BLE001  한 채널이 죽어도 나머지에는 보낸다
                log.warning("채널 하나에 실패했다. 나머지 채널은 계속 보낸다: %s", e)
                first = first or e
        if first is not None:
            raise first  # 종류(UnknownResult 등)를 그대로 올려 store가 같게 분류한다
        return "sent"


# notify·weekly가 받는 발송기. 한 채널(Webhook)이든 등록된 전부(Fanout)든 send(text) 하나면 된다.
Sender = Webhook | Fanout
