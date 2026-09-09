STATUS = {
    "todo": "시작 전",
    "doing": "진행 중",
    "paused": "일시정지",
    "blocked": "막힘",
    "review": "검토 대기",
    "done": "완료",
    "cancelled": "취소",
}
KIND_TITLE = {"d3": "D-3", "d1": "D-1", "d0": "오늘 마감", "overdue": "기한 초과"}


def mention(assignee: dict) -> str:
    did = assignee.get("discord_user_id")
    return f"<@{did}>" if did else assignee.get("display_name", "?")


def task_line(t: dict) -> str:
    reason = f" ({t['stop_reason']})" if t.get("stop_reason") else ""
    return (
        f"• **{t['number']}** {t['title']} — {t['project']['name']} — {mention(t['assignee'])}"
        f" — {STATUS.get(t['status'], t['status'])}{reason}\n  {t['url']}"
    )


def deadline_message(kind: str, tasks: list[dict], today: str) -> str:
    head = f"📌 마감 알림 · {KIND_TITLE[kind]} · {today}"
    lines = [
        task_line(t) + (f"  (기한 {t['due_date']})" if kind == "overdue" else "") for t in tasks
    ]
    return head + "\n" + "\n".join(lines)


def test_message(site_name: str) -> str:
    return f"✅ {site_name} Discord 알림 연결 테스트"
