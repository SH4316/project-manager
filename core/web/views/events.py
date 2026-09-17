"""실시간 푸시(SSE). 남이 고친 태스크가 내 화면에도 곧바로 반영되게 한다.

브라우저는 `EventSource`로 이 주소를 열어 두고, 서버는 내 조직에서 방금 바뀐 태스크의
id를 흘려보낸다. 클라이언트(app.js)가 그것을 기존 HTMX 이벤트(task-changed·task-updated)로
바꿔 쏘면, 이미 그 이벤트를 듣고 있는 행·패널·오늘 목록이 스스로 새로고침한다.
즉 템플릿은 하나도 바뀌지 않는다 — 이 파일과 app.js 몇 줄이 실시간의 전부다.

한 연결은 STREAM_SECONDS 뒤 스스로 닫는다. EventSource가 알아서 다시 붙으므로 끊김은
사용자에게 보이지 않고, 대신 죽은 스레드·프록시 유휴 종료·배포 후 낡은 연결이 쌓이지 않는다.
"""

import json
import time

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import StreamingHttpResponse
from django.utils import timezone

from tasks.models import Task

from .common import current_org

POLL_SECONDS = 2  # 변경을 확인하는 주기
STREAM_SECONDS = 50  # gunicorn --timeout(60)보다 짧게 잡아 연결을 먼저 닫는다
HEARTBEAT_SECONDS = 15  # 프록시가 유휴로 보고 끊지 않게 주석 한 줄을 보낸다


def _changed_since(org, since):
    """org의 태스크 중 since 이후에 바뀐 것.

    # ponytail: updated_at 순차 조회. ChangeLog는 본문 텍스트 자동 저장을 기록하지 않으므로
    # 그쪽을 피드로 쓰면 메모 편집이 상대 화면에 안 보인다. 팀 규모가 커져 이 질의가 무거워지면
    # updated_at에 인덱스를 두거나 Postgres LISTEN/NOTIFY로 바꾼다.
    """
    return list(
        Task.objects.filter(project__org=org, updated_at__gt=since)
        .order_by("updated_at")
        .values_list("pk", "updated_at")[:50]
    )


def _stream(org, since):
    started = time.monotonic()
    last_beat = started
    # 재연결 간격을 브라우저에 알려 둔다(기본값은 3초로 제각각이다).
    yield f"retry: {POLL_SECONDS * 1000}\n\n"
    while time.monotonic() - started < STREAM_SECONDS:
        rows = _changed_since(org, since)
        # 스트림이 사는 동안 DB 연결을 붙잡고 있지 않는다 — 보는 사람 수만큼 연결이 늘어난다.
        connection.close()
        if rows:
            since = rows[-1][1]
            for pk, _ in rows:
                yield f"data: {json.dumps({'id': pk})}\n\n"
            last_beat = time.monotonic()
        elif time.monotonic() - last_beat > HEARTBEAT_SECONDS:
            yield ": keepalive\n\n"
            last_beat = time.monotonic()
        time.sleep(POLL_SECONDS)


@login_required
def events(request):
    org = current_org(request)
    if org is None:
        # 조직이 없으면 보낼 것도 없다. 빈 스트림을 바로 닫는다.
        return StreamingHttpResponse(iter([": no org\n\n"]), content_type="text/event-stream")
    response = StreamingHttpResponse(_stream(org, timezone.now()), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # nginx/NPM이 스트림을 버퍼링하지 않게
    return response
