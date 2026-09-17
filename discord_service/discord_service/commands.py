"""DM 평문 명령 해석. core를 부르고 한국어 답장 문자열을 돌려준다.

여기에는 업무 규칙이 없다. 파싱과 문구뿐이고, 판단은 전부 core의 services가 한다.
`*_reply` 함수들은 슬래시 명령(slash.py)도 그대로 쓴다 — 파싱만 다르고 문구·오류 변환은 하나다.
"""

import logging
from datetime import date

import httpx

from .core_client import CoreClient
from .messages import HELP, STATUS, today_message

log = logging.getLogger(__name__)

NEED_NUMBER = '태스크 번호가 필요해요. 예: `완료 12` (마감 알림의 "TASK-12"에서 숫자만)'
NEED_CODE = "연결 코드가 필요해요. 웹 설정 → 프로필에서 [Discord 연결]을 누르면 나옵니다."
NEED_EXTEND = "예: `연장 12 2026-09-20 QA 지연` (번호, 새 목표일, 사유)"
BAD_DATE = "날짜 형식은 `2026-09-20` 처럼 보내 주세요."
BUSY = "지금은 처리할 수 없습니다. 잠시 뒤 다시 보내 주세요."
TOO_FAST = "요청이 많습니다. 1분 뒤 다시 보내 주세요."

# 발신자별 분당 한도. core의 처리량 제한(60/m)은 봇 계정 하나로 세므로 한 사람이
# 다 쓰면 다른 사람 명령까지 429가 된다. DM과 슬래시가 같은 통을 쓴다.
RATE = 20


def too_fast(seen: dict[str, list[float]], uid: str, now: float) -> bool:
    recent = [t for t in seen.get(uid, []) if now - t < 60]
    recent.append(now)
    seen[uid] = recent
    return len(recent) > RATE


def task_number(token: str) -> int | None:
    """`12`와 `TASK-12`를 모두 받는다(검색 화면과 같은 방식)."""
    t = (token or "").upper().replace("TASK-", "").strip()
    return int(t) if t.isdecimal() else None


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def guarded(fn, *args) -> str:
    """core 호출을 답장 문자열로 바꾼다. HTTP 오류는 한국어 문구로, 나머지는 재시도 안내로."""
    try:
        return fn(*args)
    except httpx.HTTPStatusError as e:
        return _error_reply(e.response)
    except httpx.HTTPError as e:
        log.warning("core 호출 실패: %s", e)
        return BUSY


def handle(core: CoreClient, author_id: str, text: str) -> str:
    parts = (text or "").strip().split()
    if not parts:
        return HELP
    cmd, args = parts[0], parts[1:]
    return guarded(_dispatch, core, author_id, cmd, args)


def _dispatch(core: CoreClient, author_id: str, cmd: str, args: list[str]) -> str:
    if cmd in ("연결", "link"):
        if not args:
            return NEED_CODE
        return link_reply(core, author_id, args[0])
    if cmd in ("연결해제", "unlink"):
        return unlink_reply(core, author_id)
    if cmd in ("오늘", "today"):
        return today_reply(core, author_id)
    if cmd in ("완료", "done"):
        num = task_number(args[0]) if args else None
        if num is None:
            return NEED_NUMBER
        return done_reply(core, author_id, num)
    if cmd in ("연장", "extend"):
        num = task_number(args[0]) if args else None
        if num is None or len(args) < 2:
            return NEED_EXTEND
        due = parse_date(args[1])
        if due is None:
            return BAD_DATE
        return extend_reply(core, author_id, num, due, " ".join(args[2:]))
    return HELP


# --- 답장 문구. DM과 슬래시가 공유한다 ---


def _head(t: dict) -> str:
    return f"**{t['number']}** {t['title']}"


def link_reply(core: CoreClient, did: str, code: str) -> str:
    name = core.link(code, did).get("display_name", "")
    return f"{name} 계정과 연결했습니다. `오늘` 을 보내 보세요."


def unlink_reply(core: CoreClient, did: str) -> str:
    core.unlink(did)
    return "연결을 끊었습니다. 마감 알림 DM도 멈춥니다."


def today_reply(core: CoreClient, did: str) -> str:
    return today_message(core.today(did))


def done_reply(core: CoreClient, did: str, num: int) -> str:
    r = core.done(did, num)
    return f"{_head(r['task'])} — {r['was']} → 완료로 바꿨습니다."


def extend_reply(core: CoreClient, did: str, num: int, due: date, reason: str) -> str:
    t = core.extend(did, num, due.isoformat(), reason)["task"]
    return f"{_head(t)} — 목표일을 {t['due_date']}로 미뤘습니다."


def create_reply(core: CoreClient, did: str, fields: dict) -> str:
    t = core.create_task(did, fields)["task"]
    due = t["due_date"] or "기한 미정"
    return f"{_head(t)} 을(를) 만들었습니다 — {t['project']['name']} · {due}\n{t['url']}"


def update_reply(core: CoreClient, did: str, num: int, changes: dict) -> str:
    if not changes:
        return "바꿀 항목을 하나 이상 넣어 주세요."
    t = core.update_task(did, num, changes)["task"]
    return f"{_head(t)} — 수정했습니다.\n{t['url']}"


def note_reply(core: CoreClient, did: str, num: int, text: str) -> str:
    t = core.note(did, num, text)["task"]
    return f"{_head(t)} — 진행 메모에 덧붙였습니다."


def status_reply(core: CoreClient, did: str, num: int, status: str, reason: str) -> str:
    r = core.status(did, num, status, reason)
    label = STATUS.get(status, status)
    return f"{_head(r['task'])} — {r['was']} → {label}(으)로 바꿨습니다."


def _error_reply(r: httpx.Response) -> str:
    detail = _detail(r)
    if r.status_code == 404:
        return detail or "찾을 수 없습니다. `연결`이 필요할 수 있습니다."
    if r.status_code == 403:
        return "권한이 없습니다."
    if r.status_code == 409:
        return "방금 다른 곳에서 변경되었습니다. 다시 보내 주세요."
    if r.status_code == 429:
        return TOO_FAST
    if r.status_code == 400:
        return detail or "입력을 다시 확인해 주세요."
    log.warning("core %s: %s", r.status_code, detail)
    return BUSY


def _detail(r: httpx.Response) -> str:
    """`{"detail": "문구"}`(HttpError)와 `{"detail": {필드: 문구}}`(ServiceError) 둘 다."""
    try:
        d = r.json().get("detail")
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(d, str):
        return d
    if isinstance(d, dict):
        return " ".join(str(v) for v in d.values())
    return ""
