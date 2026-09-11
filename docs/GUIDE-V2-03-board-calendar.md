# 구현 지시서 V2-03: 칸반 드래그와 일정 캘린더 (3단계)

목표 셋. 보드에서 카드를 끌어 상태를 바꾼다. 일정 카드에서 시간표를 없애고 월 캘린더만 남기되 달을 넘길 수 있게 한다. 프로젝트 타일에 경고색을 넣는다.

**새 엔드포인트를 만들지 않는다.** 드롭은 기존 `POST /tasks/{id}/status`를 그대로 부른다. 상태 전이 규칙은 한 곳에만 있어야 한다.

---

## 1. Step 1. 보드 열

목업의 열은 여섯이다. 시작 전 · 진행 중 · 검토 대기 · 막힘 · 일시정지 · **완료**. "모든 상태가 열로 존재해야 한다 — 열 밖 상태가 생기면 카드가 사라진다"가 규칙이다. 완료 열이 없으면 드래그로 완료할 수 없으므로 **완료는 항상 그린다.** 취소는 `include_closed`일 때만 열이 생긴다.

`web/views/projects.py`:

```python
BOARD_OPEN = ["todo", "doing", "review", "blocked", "paused"]
# ponytail: 완료 열은 최근 20건만 보여 준다. 전부 보려면 목록 보기의 '완료·취소 포함'을 쓴다.
DONE_ON_BOARD = 20


def board_context(request, project, include_closed: bool) -> dict:
    """보드 부분 렌더 context. 목록 보기와 달리 완료를 항상 실어 온다."""
    labels = dict(Task.STATUSES)
    codes = BOARD_OPEN + ["done"] + (["cancelled"] if include_closed else [])
    base = project.tasks.select_related("project", "assignee")
    open_tasks = sorted(base.filter(status__in=Task.OPEN), key=ts.by_due)
    done_tasks = list(base.filter(status="done").order_by("-completed_at", "-id")[:DONE_ON_BOARD])
    extra = list(base.filter(status="cancelled").order_by("-id")) if include_closed else []
    rows = rows_for(request.user, open_tasks + done_tasks + extra, "board")
    return {
        "project": project,
        "include_closed": include_closed,
        "columns": [(c, labels[c], [r for r in rows if r["task"].status == c]) for c in codes],
    }
```

`project_detail`은 목록일 때 지금 로직을 유지하고, 보드일 때 `board_context`를 쓴다. 그리고 부분 렌더를 받는다.

```python
    if request.GET.get("part") == "board":
        return render(request, "projects/_board.html", board_context(request, project, include_closed))
```

`templates/projects/_board.html`:

```html
<div id="board" class="board" data-include-closed="{% if include_closed %}1{% endif %}">
  {% for code, label, col in columns %}
  <div class="col" data-status="{{ code }}">
    <h3>{{ label }} <span class="muted">{{ col|length }}</span></h3>
    <ul class="tasks">{% for r in col %}{% task_row r %}{% endfor %}</ul>
    {% if not col %}<span class="t12" style="color:var(--text-disabled)">여기로 끌어다 놓기</span>{% endif %}
  </div>
  {% endfor %}
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
</div>
```

`projects/detail.html`의 보드 갈래를 `{% include "projects/_board.html" %}`로 바꾼다.

---

## 2. Step 2. 행에 드래그 속성

`row_ctx`의 `ROW_OPTS`에 `board`를 더하고 context에 `"in_board": "board" in o`를 넣는다.

`tasks/_row.html`의 `<li>`에 조건부 속성을 더한다.

```html
<li id="task-{{ task.pk }}"
    class="task-row{% if task.is_closed %} closed{% endif %}{% if selected %} selected{% endif %}"
    role="button" tabindex="0" aria-label="{{ task.title }} 상세 보기"
    data-id="{{ task.pk }}" data-panel="{% url 'task_panel' task.pk %}"
    {% if in_board %}draggable="true" data-version="{{ task.version }}" data-status="{{ task.status }}"{% endif %}
    {% if not in_today_page and not in_board %}hx-get="..." hx-trigger="task-changed[...] from:body" hx-swap="outerHTML"{% endif %}>
```

보드에서는 행이 스스로 갱신하지 않는다. 드롭 응답이 보드 전체를 다시 그리기 때문이다.

행 안의 상태 select는 **그대로 둔다.** 모바일 브라우저는 HTML5 드래그를 지원하지 않으므로 그것이 유일한 상태 변경 수단이다.

---

## 3. Step 3. 드래그 (`app.js`)

```js
  // 칸반 드래그. 드롭은 상태 전환이므로 기존 엔드포인트를 그대로 부른다.
  var dragId = null;
  function csrf() {
    try { return JSON.parse(body.getAttribute("hx-headers") || "{}")["X-CSRFToken"]; }
    catch (e) { return ""; }
  }
  function clearOver() {
    Array.prototype.forEach.call(document.querySelectorAll(".col.over"), function (c) {
      c.classList.remove("over");
    });
  }
  body.addEventListener("dragstart", function (e) {
    var card = e.target.closest && e.target.closest("li[draggable='true'][data-id]");
    if (!card) return;
    dragId = card.dataset.id;
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
    card.classList.add("dragging");
  });
  body.addEventListener("dragend", function (e) {
    dragId = null;
    if (e.target.classList) e.target.classList.remove("dragging");
    clearOver();
  });
  body.addEventListener("dragover", function (e) {
    var col = e.target.closest && e.target.closest(".col[data-status]");
    if (!col || !dragId) return;
    e.preventDefault();
    if (!col.classList.contains("over")) { clearOver(); col.classList.add("over"); }
  });
  body.addEventListener("drop", function (e) {
    var col = e.target.closest && e.target.closest(".col[data-status]");
    if (!col || !dragId) return;
    e.preventDefault();
    clearOver();
    var id = dragId, to = col.dataset.status;
    dragId = null;
    var card = document.getElementById("task-" + id);
    if (!card || card.dataset.status === to) return;
    // 막힘은 사유가 필수다. 보내지 않고 패널의 사유 박스를 연다(상태 select와 같은 규칙).
    if (to === "blocked") { openPanel("/tasks/" + id + "/panel?block=1", "/tasks/" + id); return; }
    var board = document.getElementById("board");
    htmx.ajax("POST", "/tasks/" + id + "/status", {
      target: "#board", swap: "outerHTML",
      headers: { "X-CSRFToken": csrf() },
      values: {
        status: to, version: card.dataset.version, from: "board",
        include_closed: board ? board.dataset.includeClosed : "",
      },
    });
  });
```

일시정지로 떨어뜨리면 **바로 전환한다.** 일시정지 사유는 선택이라는 09-10 결정을 드래그가 바꾸지 않는다. 전환 뒤 패널을 열면 사유 박스가 있다.

`app.css`:

```css
.board .col { display: flex; flex-direction: column; gap: 8px; min-height: 120px; padding: 8px; border: 1px dashed var(--border); border-radius: 8px; }
.board .col.over { background: var(--primary-bg); border-color: var(--primary); border-style: solid; }
.task-row[draggable="true"] { cursor: grab; }
.task-row.dragging { opacity: .4; }
```

---

## 4. Step 4. 서버 응답 (`from=board`)

`web/views/tasks.py`의 `_respond`에 갈래를 하나 더한다.

```python
def _respond(request, task, origin, error=None):
    """origin: 'row'(기본) | 'panel' | 'head' | 'board'."""
    if origin == "panel":
        return _panel(request, task, error=error)
    if origin == "head":
        from .today import head
        return head(request, error=error)
    if origin == "board":
        from .projects import board_context
        ctx = board_context(request, task.project, request.POST.get("include_closed") == "1")
        ctx["error"] = error
        return render(request, "projects/_board.html", ctx)
    return render_row(request, task, error=error)
```

성공하면 지금처럼 `HX-Trigger: task-updated`를 붙인다. 오류(기한 없이 진행 중, 사유 없이 막힘, 버전 충돌)는 보드를 다시 그리면서 카드가 제자리로 돌아가고 아래에 메시지가 뜬다.

---

## 5. Step 5. 일정 카드 — 월 캘린더만

**지우는 것**: `views/today.py`의 `HOURS`, `cal_mode`, `due_today_tasks`, `_schedule`의 `cal` 파라미터. `today/_schedule.html`의 시간표 갈래와 보기 전환 버튼. `app.css`의 `.hours`.

`_schedule`를 다시 쓴다.

```python
def _schedule(request, day: date) -> dict:
    """일정 카드. 월 캘린더만 있다. ?month=YYYY-MM&day=YYYY-MM-DD"""
    raw = request.GET.get("month", "")
    try:
        month = date.fromisoformat(f"{raw}-01") if raw else day.replace(day=1)
    except ValueError:
        month = day.replace(day=1)
    try:
        sel = date.fromisoformat(request.GET.get("day", "")) if request.GET.get("day") else day
    except ValueError:
        sel = day

    my_open = ts.visible_tasks(request.user).filter(assignee=request.user, status__in=Task.OPEN)
    counts = dict(
        my_open.filter(due_date__year=month.year, due_date__month=month.month)
        .values_list("due_date")
        .annotate(n=Count("id"))
    )
    cells_src = week_days(month)
    while len(cells_src) % 7:          # 28·35·42 중 하나가 되도록 뒤를 채운다
        cells_src.append(None)

    def url(d: date, m: date | None = None) -> str:
        m = m or month
        return f"{reverse('today')}?schedule=1&month={m:%Y-%m}&day={d.isoformat()}"

    sel_in_month = (sel.year, sel.month) == (month.year, month.month)
    sel_tasks = sorted(my_open.filter(due_date=sel), key=ts.by_due) if sel_in_month else []
    prev_m = (month.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_m = date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)
    this_m = day.replace(day=1)

    if not sel_in_month:
        sel_label = "날짜를 누르면 그날 마감이 보입니다"
    elif sel_tasks:
        sel_label = f"{fmt_md(sel)} 마감 {len(sel_tasks)}건"
    else:
        sel_label = f"{fmt_md(sel)} 마감 없음"

    return {
        "cal_title": f"{month.year}년 {month.month}월",
        "cal_prev": url(prev_m, prev_m),
        "cal_next": url(next_m, next_m),
        "cal_this": url(this_m, this_m) if month != this_m else "",
        "cal_cells": [
            None
            if d is None
            else {
                "day": d.day,
                "n": counts.get(d, 0),
                "today": d == day,
                "sel": sel_in_month and d == sel,
                "url": url(d),
                "aria": f"{d.month}월 {d.day}일 마감 {counts.get(d, 0)}건",
            }
            for d in cells_src
        ],
        "cal_sel_label": sel_label,
        "cal_sel_tasks": sel_tasks,
    }
```

`counts`의 키가 `date`인지 확인한다. SQLite와 Postgres 모두 `values_list("due_date")`는 `date`를 준다.

`today/_schedule.html`:

```html
<section class="card schedule" aria-label="일정">
  <div class="card-head">
    <h2>일정</h2>
    <div class="row" style="gap:4px">
      <a class="btn sm icon" href="{{ cal_prev }}" aria-label="이전 달" title="이전 달">‹</a>
      <span class="t13" style="min-width:96px;text-align:center;font-weight:600">{{ cal_title }}</span>
      <a class="btn sm icon" href="{{ cal_next }}" aria-label="다음 달" title="다음 달">›</a>
      {% if cal_this %}<a class="btn sm" href="{{ cal_this }}">이번 달</a>{% endif %}
    </div>
  </div>
  <div class="cal">
    {% for w in "월화수목금토일" %}<span class="muted t12">{{ w }}</span>{% endfor %}
    {% for c in cal_cells %}
      {% if c %}<a href="{{ c.url }}" class="{% if c.today %}today{% endif %}{% if c.sel %} sel{% endif %}" aria-label="{{ c.aria }}">{{ c.day }}{% if c.n %}<small>●{{ c.n }}</small>{% endif %}</a>
      {% else %}<span></span>{% endif %}
    {% endfor %}
  </div>
  <div class="muted t13">{{ cal_sel_label }}</div>
  <ul class="stack">
    {% for t in cal_sel_tasks %}
    <li><button type="button" class="btn link" hx-get="{% url 'task_panel' t.pk %}" hx-target="#panel" hx-swap="innerHTML" hx-push-url="{% url 'task_detail' t.pk %}">{{ t.title }}</button></li>
    {% endfor %}
  </ul>
</section>
```

`_list.html`의 [일정 보기] 토글은 그대로 둔다.

---

## 6. Step 6. 프로젝트 타일 경고색

`projects/detail.html`의 타일 다섯 중 **기한 초과**와 **막힘**만 값이 0보다 클 때 `--danger`로 그린다.

```html
<div class="tile"><b{% if stats.overdue %} class="danger"{% endif %}>{{ stats.overdue }}</b><span>기한 초과</span></div>
<div class="tile"><b{% if stats.blocked %} class="danger"{% endif %}>{{ stats.blocked }}</b><span>막힘</span></div>
```

---

## 7. 테스트

| 이름 | 확인 |
|---|---|
| `test_board_always_has_done_column` | `include_closed`가 꺼져 있어도 완료 열이 있고 취소 열은 없다 |
| `test_board_columns_cover_all_statuses` | `include_closed`면 7개 열이 `Task.STATUSES`를 전부 덮는다 |
| `test_board_part_renders_only_board` | `?part=board`가 `id="board"`로 시작하는 조각을 준다 |
| `test_drop_changes_status_and_returns_board` | `from=board` POST가 200 + `id="board"` + 상태 변경 + `HX-Trigger` |
| `test_drop_to_doing_without_due_shows_error_in_board` | 기한 없는 태스크를 진행 중으로 떨구면 보드에 오류 문구 |
| `test_drop_blocked_without_reason_shows_error_in_board` | 서버도 막는다(클라이언트는 패널로 보내지만 규칙은 서버에 있다) |
| `test_drop_conflict_shows_message_in_board` | 낡은 version이면 충돌 안내 |
| `test_row_draggable_only_in_board` | `board` opts일 때만 `draggable` |
| `test_schedule_has_no_time_view` | `?cal=time`을 줘도 시간표가 없고 월 캘린더가 나온다 |
| `test_schedule_cells_multiple_of_seven` | 28·35·42 중 하나 |
| `test_schedule_month_nav` | 이전·다음 달 링크가 달을 바꾸고, 이번 달이면 [이번 달]이 없다 |
| `test_schedule_labels` | 마감 있음·없음·선택일 없음 세 문구 |
| `test_schedule_counts_exclude_closed` | 완료·취소는 `●N`에 안 센다 |

## 8. 검증

```bash
cd core && uv run ruff check . && uv run pytest -q
```

브라우저에서: 보드에서 카드를 다른 열로 끌면 상태가 바뀌고 이력에 남는다. 막힘 열로 끌면 사유 박스가 열리고, 취소하면 상태가 그대로다. 기한 없는 태스크를 진행 중으로 끌면 오류가 뜨고 카드가 제자리로 간다. 일정에서 ‹ › 로 달을 넘기고 [이번 달]로 돌아온다.

## 9. 완료 체크

- [ ] 완료 열이 항상 있고 모든 상태가 열로 존재한다
- [ ] 드롭이 기존 `status` 엔드포인트를 쓴다(새 엔드포인트 없음)
- [ ] 막힘 드롭은 사유를 받는다
- [ ] 시간표 코드가 남아 있지 않다(`grep -rn "HOURS\|cal_mode" core`가 비어 있다)
- [ ] 캘린더 달 이동과 세 가지 라벨
