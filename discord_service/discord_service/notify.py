import logging
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import Sender, UnknownResult
from .messages import deadline_message
from .store import Store

log = logging.getLogger(__name__)
OPEN = ("todo", "doing", "paused", "blocked", "review")


def classify(task: dict, today: date) -> str | None:
    """오늘 기준 이 태스크에 보낼 알림 종류. 없으면 None."""
    if not task.get("due_date") or task["status"] not in OPEN:
        return None
    due = date.fromisoformat(task["due_date"])
    delta = (due - today).days
    if delta == 3:
        return "d3"
    if delta == 1:
        return "d1"
    if delta == 0:
        return "d0"
    if delta < 0:
        return "overdue"
    return None


def run_deadlines(core: CoreClient, hook: Sender, store: Store, team_id: int, today: date) -> dict:
    """하루 1회. 결과 dict: {sent, skipped, failed, unknown}."""
    today_s = today.isoformat()
    result = {"sent": 0, "skipped": 0, "failed": 0, "unknown": 0}
    candidates = core.open_tasks(team_id, due_to=(today + timedelta(days=3)).isoformat())

    per_kind: dict[str, list[dict]] = {"d3": [], "d1": [], "d0": [], "overdue": []}
    for t in candidates:
        kind = classify(t, today)
        if kind:
            per_kind[kind].append(t)

    # D-3 / D-1 / 당일: 태스크별 개별 메시지, (task, kind, due_date) 단위 중복 방지
    for kind in ("d3", "d1", "d0"):
        for t in per_kind[kind]:
            if not store.claim(t["id"], kind, t["due_date"]):
                result["skipped"] += 1
                continue
            try:
                fresh = core.task(t["id"])  # 발송 직전 재확인 (A09, A10)
            except Exception as e:  # noqa: BLE001
                # 자리를 잡아 둔 채 예외가 나가면 그 알림은 영구히 안 나간다. 놓아주고 다음 tick에 다시 시도.
                store.release(t["id"], kind, t["due_date"])
                result["skipped"] += 1
                log.warning("재확인 실패, 다음 실행에서 재시도: %s %s: %s", kind, t["id"], e)
                continue
            if (
                fresh is None
                or classify(fresh, today) != kind
                or fresh["due_date"] != t["due_date"]
            ):
                store.release(t["id"], kind, t["due_date"])
                result["skipped"] += 1
                continue
            _send(
                hook,
                store,
                deadline_message(kind, [fresh], today_s),
                t["id"],
                kind,
                t["due_date"],
                result,
            )

    # 기한 초과: 하루 1건 묶음
    if per_kind["overdue"]:
        if store.claim_daily("overdue", today_s):
            fresh_list = []
            try:
                for t in per_kind["overdue"]:
                    fresh = core.task(t["id"])
                    if fresh and classify(fresh, today) == "overdue":
                        fresh_list.append(fresh)
            except Exception as e:  # noqa: BLE001
                # 하루치 자리를 놓아주어 다음 tick에 다시 시도한다.
                store.release_daily("overdue", today_s)
                result["skipped"] += 1
                log.warning("기한 초과 재확인 실패, 다음 실행에서 재시도: %s", e)
                return result
            if fresh_list:
                fresh_list.sort(key=lambda x: (x["due_date"], x["id"]))
                _send(
                    hook,
                    store,
                    deadline_message("overdue", fresh_list, today_s),
                    0,
                    "overdue",
                    today_s,
                    result,
                )
            else:
                store.release_daily("overdue", today_s)
        else:
            result["skipped"] += 1
    return result


def _send(hook, store, text, task_id, kind, due_date, result):
    if task_id:
        pass  # claim은 호출자가 했다
    else:
        store.claim(0, kind, due_date)
    try:
        hook.send(text)
        store.mark(task_id, kind, due_date, "sent")
        result["sent"] += 1
    except UnknownResult as e:
        store.mark(task_id, kind, due_date, "unknown", str(e))
        result["unknown"] += 1
        log.warning("발송 결과 불명확: %s %s", kind, task_id)
    except Exception as e:  # noqa: BLE001
        store.mark(task_id, kind, due_date, "failed", str(e))
        result["failed"] += 1
        log.error("발송 실패: %s %s: %s", kind, task_id, e)
