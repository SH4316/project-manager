import logging
from collections import defaultdict
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import Bot, ChannelOpenFailed, DmBlocked, UnknownResult
from .messages import deadline_message, dm_blocked_message
from .store import Store

log = logging.getLogger(__name__)
OPEN = ("todo", "doing", "paused", "blocked", "review")
KINDS = ("d3", "d1", "d0", "overdue")


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


def run_deadlines(core: CoreClient, bot: Bot, store: Store, org_id: int, today: date) -> dict:
    """하루 1회. 담당자별 개인 DM으로 보낸다.

    한 사람이 하루에 받는 DM은 종류당 1건, 최대 4건이다(D-3·D-1·당일·기한 초과).
    태스크마다 한 통씩 보내면 아침에 DM 폭탄이 되고 Discord Developer Policy의
    '원치 않는 반복 DM'에 걸린다.
    """
    today_s = today.isoformat()
    result = {
        "sent": 0,
        "skipped": 0,
        "failed": 0,
        "unknown": 0,
        "unlinked": 0,
        # 자리를 놓아준 것들. 하루 1회 문턱(claim_daily)을 다시 열어야 실제로 재시도된다.
        "open_failed": 0,
        "recheck_failed": 0,
    }
    unlinked_names: list[str] = []
    candidates = core.open_tasks(org_id, due_to=(today + timedelta(days=3)).isoformat())

    # (종류, 담당자) 로 묶는다. 담당자는 태스크당 한 명이다.
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for t in candidates:
        kind = classify(t, today)
        assignee = t.get("assignee") or {}
        if kind and assignee.get("id"):
            grouped[(kind, assignee["id"])].append(t)

    for kind in KINDS:
        for uid in sorted(u for (k, u) in grouped if k == kind):
            tasks = grouped[(kind, uid)]
            assignee = tasks[0]["assignee"]
            did = assignee.get("discord_user_id")
            if not did:
                # 자리를 잡지 않는다. 나중에 연결하면 그 다음 알림부터 정상으로 받는다.
                result["unlinked"] += 1
                name = assignee.get("display_name") or str(uid)
                if name not in unlinked_names:
                    unlinked_names.append(name)
                log.warning("Discord 미연결이라 DM을 못 보낸다: %s", assignee.get("display_name"))
                continue
            key = f"{kind}:{uid}"
            if not store.claim(0, key, today_s):
                result["skipped"] += 1
                continue
            try:
                fresh = [core.task(t["id"]) for t in tasks]  # 발송 직전 재확인 (A09, A10)
            except Exception as e:  # noqa: BLE001
                # 자리를 잡아 둔 채 나가면 그 알림은 영구히 안 나간다. 놓아준다.
                # skipped(이미 보냄·더 이상 해당 없음)와 섞으면 손실이 안 보이므로 따로 센다 —
                # 이 숫자가 0이 아니면 scheduler가 그날 문턱을 다시 열고 /ops를 빨강으로 만든다.
                store.release(0, key, today_s)
                result["recheck_failed"] += 1
                log.warning("재확인 실패, 이 틱 뒤에 다시 훑는다: %s: %s", key, e)
                continue
            live = [f for f in fresh if f and classify(f, today) == kind]
            if not live:
                store.release(0, key, today_s)
                result["skipped"] += 1
                continue
            live.sort(key=lambda x: (x["due_date"], x["id"]))
            _send_dm(bot, store, did, deadline_message(kind, live, today_s), key, today_s, result)

    result["unlinked_names"] = unlinked_names
    return result


def _send_dm(bot, store, did, text, key, day, result):
    try:
        bot.send_dm(did, text)
        store.mark(0, key, day, "sent")
        result["sent"] += 1
    except ChannelOpenFailed as e:
        # 아직 아무것도 보내지 않았다. 자리를 놓아준다(scheduler가 그날 문턱을 다시 연다).
        store.release(0, key, day)
        result["open_failed"] += 1
        log.warning("DM 채널을 열지 못했다, 다음 실행에서 재시도: %s: %s", key, e)
    except DmBlocked as e:
        # 영구 실패다. 자리를 남겨 다음 틱에 다시 시도하지 않는다(403은 invalid-request 예산을 태운다).
        store.mark(0, key, day, "failed", str(e))
        result["failed"] += 1
        log.error("DM 거부: %s %s", key, e)
        _notify_channel_once(bot, store, did, day)
    except UnknownResult as e:
        store.mark(0, key, day, "unknown", str(e))
        result["unknown"] += 1
        log.warning("발송 결과 불명확: %s", key)
    except Exception as e:  # noqa: BLE001
        store.mark(0, key, day, "failed", str(e))
        result["failed"] += 1
        log.error("발송 실패: %s: %s", key, e)


def _notify_channel_once(bot, store, did, day):
    """DM이 막힌 사람에게는 조직 채널로 하루 한 번만 알린다. 태스크 내용은 넣지 않는다."""
    if not store.claim(0, f"dmblocked:{did}", day):
        return
    try:
        bot.send_channel(dm_blocked_message({"discord_user_id": did}))
        store.mark(0, f"dmblocked:{did}", day, "sent")
    except Exception as e:  # noqa: BLE001
        store.mark(0, f"dmblocked:{did}", day, "failed", str(e))
        log.error("DM 거부 통보 실패: %s", e)
