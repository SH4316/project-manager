"""DM 평문 명령 해석. core를 부르고 한국어 답장 문자열을 돌려준다.

여기에는 업무 규칙이 없다. 파싱과 문구뿐이고, 판단은 전부 core의 services가 한다.
"""

import logging
from datetime import date

import httpx

from .core_client import CoreClient
from .messages import HELP, today_message

log = logging.getLogger(__name__)

NEED_NUMBER = '태스크 번호가 필요해요. 예: `완료 12` (마감 알림의 "TASK-12"에서 숫자만)'
NEED_CODE = "연결 코드가 필요해요. 웹 설정 → 프로필에서 [Discord 연결]을 누르면 나옵니다."
NEED_EXTEND = "예: `연장 12 2026-09-20 QA 지연` (번호, 새 목표일, 사유)"


def task_number(token: str) -> int | None:
    """`12`와 `TASK-12`를 모두 받는다(검색 화면과 같은 방식)."""
    t = (token or "").upper().replace("TASK-", "").strip()
    return int(t) if t.isdecimal() else None


def handle(core: CoreClient, author_id: str, text: str) -> str:
    parts = (text or "").strip().split()
    if not parts:
        return HELP
    cmd, args = parts[0], parts[1:]
    try:
        return _dispatch(core, author_id, cmd, args)
    except httpx.HTTPStatusError as e:
        return _error_reply(e.response)
    except httpx.HTTPError as e:
        log.warning("core 호출 실패: %s", e)
        return "지금은 처리하지 못했어요. 잠시 뒤 다시 보내 주세요."


def _dispatch(core: CoreClient, author_id: str, cmd: str, args: list[str]) -> str:
    if cmd in ("연결", "link"):
        if not args:
            return NEED_CODE
        name = core.link(args[0], author_id).get("display_name", "")
        return f"{name} 계정과 연결했습니다. `오늘` 을 보내 보세요."
    if cmd in ("연결해제", "unlink"):
        core.unlink(author_id)
        return "연결을 끊었습니다. 마감 알림 DM도 멈춥니다."
    if cmd in ("오늘", "today"):
        return today_message(core.today(author_id))
    if cmd in ("완료", "done"):
        num = task_number(args[0]) if args else None
        if num is None:
            return NEED_NUMBER
        r = core.done(author_id, num)
        t = r["task"]
        return f"**{t['number']}** {t['title']} — {r['was']} → 완료로 바꿨습니다."
    if cmd in ("연장", "extend"):
        num = task_number(args[0]) if args else None
        if num is None or len(args) < 2:
            return NEED_EXTEND
        try:
            due = date.fromisoformat(args[1])
        except ValueError:
            return "날짜 형식은 `2026-09-20` 처럼 보내 주세요."
        reason = " ".join(args[2:])
        t = core.extend(author_id, num, due.isoformat(), reason)["task"]
        return f"**{t['number']}** {t['title']} — 목표일을 {t['due_date']}로 미뤘습니다."
    return HELP


def _error_reply(r: httpx.Response) -> str:
    detail = _detail(r)
    if r.status_code == 404:
        return detail or "찾을 수 없습니다. `연결` 이 필요할 수 있어요."
    if r.status_code == 403:
        return "권한이 없습니다."
    if r.status_code == 409:
        return "방금 다른 곳에서 바뀌었어요. 다시 보내 주세요."
    if r.status_code == 429:
        return "요청이 몰렸어요. 1분 뒤 다시 보내 주세요."
    if r.status_code == 400:
        return detail or "입력을 다시 확인해 주세요."
    log.warning("core %s: %s", r.status_code, detail)
    return "지금은 처리하지 못했어요. 잠시 뒤 다시 보내 주세요."


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
