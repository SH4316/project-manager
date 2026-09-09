from .messages import mention


def fixed_summary(data: dict) -> str:
    """LLM 없이 만드는 고정 형식 보고서."""
    c = data["counts"]
    head = (
        f"📊 주간 업데이트 · {data['team']['name']} · "
        f"{data['period_start']} ~ {data['period_end']} (직전 주)"
    )
    quiet = (
        c["completed"] == 0
        and c["reopened"] == 0
        and c["overdue"] == 0
        and c["blocked"] == 0
        and c["due_this_week"] == 0
    )
    if quiet:
        return head + "\n특이 사항 없음. 미완료 " + str(c["open"]) + "건."

    def section(title, items, extra=None):
        if not items:
            return ""
        lines = [f"**{title}** ({len(items)})"]
        for t in items:
            s = f"• {t['number']} {t['title']} — {t['project']['name']} — {mention(t['assignee'])}"
            if extra:
                s += extra(t)
            lines.append(s)
        return "\n".join(lines) + "\n"

    body = [
        head,
        "",
        section("지난주 완료", data["completed"]),
        section("지난주 재개", data["reopened"]),
        section("이번 주 마감", data["due_this_week"], lambda t: f" — {t['due_date']}"),
        section("기한 초과", data["overdue"], lambda t: f" — 기한 {t['due_date']}"),
        section("막힘", data["blocked"]),
    ]
    proj = [
        f"• {p['project']['name']}: 완료 {p['completed']} · 미완료 {p['open']} · "
        f"초과 {p['overdue']} · 막힘 {p['blocked']}"
        for p in data["by_project"]
    ]
    if proj:
        body.append("**프로젝트별**\n" + "\n".join(proj))
    body.append(f"검토 대기 {c['review']}건 · 기한 미정 {c['no_due']}건")
    return "\n".join(b for b in body if b is not None)


def summarize(data: dict, provider: str) -> tuple[str, str]:
    """(요약문, source). provider가 비어 있거나 실패하면 고정 형식."""
    if not provider:
        return fixed_summary(data), "fixed"
    try:
        text = _llm(data, provider)
        if not text or not text.strip():
            raise RuntimeError("empty")
        return text.strip(), "llm"
    except Exception:  # noqa: BLE001
        return fixed_summary(data), "fixed"


def _llm(data: dict, provider: str) -> str:
    # ponytail: 제공업체 미정. 정해지면 여기 분기 하나만 추가한다. 다른 파일은 손대지 않는다.
    raise NotImplementedError(f"LLM provider not configured: {provider}")
