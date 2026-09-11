# 구현 지시서 V2-05: 회의록 (5단계)

목표: 조직 안에서 회의록을 쓰고 본다. 편집기는 Notion식으로 **렌더된 줄을 누르면 그 줄만 원문 입력칸이 된다.** 태스크 패널의 "참고 자료"에서 회의록을 참조한다.

SPEC의 "Notion을 회의록 저장소로 유지"는 폐기됐다. 회의록은 앱 안에서 관리하고 Notion은 외부 링크로만 남는다.

> **마크다운 라이브러리를 쓰지 않는다.** 서버는 마크다운을 **텍스트로만** 저장하고 화면에 그릴 때도 텍스트로 내보낸다. 문서를 그리는 것은 클라이언트 렌더러 하나뿐이다. 렌더러는 `createElement`와 `textContent`만 쓰므로 XSS가 원천적으로 없다. **`innerHTML`을 한 번도 쓰지 않는다.**

---

## 1. Step 1. `notes` 앱

```bash
cd core && uv run python manage.py startapp notes
```

`config/settings.py`의 `INSTALLED_APPS`에 `"notes"`를 `tasks` 뒤에 넣는다.

`notes/models.py`:

```python
from django.conf import settings
from django.db import models

from common.dates import today_kst


class MeetingNote(models.Model):
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="notes")
    # 프로젝트가 없으면 "팀 공통" 회의록이다.
    project = models.ForeignKey(
        "projects.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="notes"
    )
    title = models.CharField("제목", max_length=200, default="제목 없는 회의록")
    body_md = models.TextField("본문", blank=True)
    # 회의를 한 날. 사용자가 고친다. created_at(기록 시각)과 다르다.
    created_on = models.DateField("생성일", default=today_kst)
    version = models.PositiveIntegerField(default=1)
    tasks = models.ManyToManyField("tasks.Task", blank=True, related_name="notes")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_on", "-id"]

    def __str__(self):
        return self.title
```

`version`은 태스크·프로젝트와 같은 낙관적 잠금이다. 제목·프로젝트·생성일·본문 중 무엇을 저장하든 1씩 오른다. **버전 이력 화면은 만들지 않는다.**

---

## 2. Step 2. `notes/services.py`

```python
import re

from django.db import transaction
from django.utils import timezone

from common.errors import ConflictError, ServiceError
from orgs.services import is_admin, is_member, orgs_of

from .models import MeetingNote

EDITABLE = {"title", "project", "created_on", "body_md"}
MAX_BODY = 256 * 1024      # 256KB. 회의록 한 편이 이보다 클 이유가 없다.


def visible_notes(user):
    return MeetingNote.objects.filter(org__in=orgs_of(user))


def get_visible_note(user, note_id: int):
    return visible_notes(user).select_related("project", "created_by", "org").filter(pk=note_id).first()


def _check_project(org, project):
    if project is not None and project.org_id != org.pk:
        raise ServiceError({"project": "같은 조직의 프로젝트여야 합니다."})


def create_note(*, org, actor, title="제목 없는 회의록", project=None, body_md="", created_on=None):
    if not is_member(actor, org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    _check_project(org, project)
    return MeetingNote.objects.create(
        org=org,
        project=project,
        title=(title or "").strip()[:200] or "제목 없는 회의록",
        body_md=(body_md or "").replace("\r\n", "\n"),
        created_on=created_on or None,
        created_by=actor,
    )


@transaction.atomic
def update_note(note, field: str, value, *, actor, expected_version: int) -> MeetingNote:
    """한 번에 한 항목. 버전이 다르면 ConflictError(최신 객체)."""
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if field not in EDITABLE:
        raise ServiceError({field: "수정할 수 없는 항목입니다."})
    if field == "title":
        value = (value or "").strip()[:200] or "제목 없는 회의록"
    elif field == "body_md":
        value = (value or "").replace("\r\n", "\n")
        if len(value.encode()) > MAX_BODY:
            raise ServiceError({"body_md": "본문이 너무 깁니다 (256KB 상한)."})
    elif field == "project":
        _check_project(note.org, value)
    elif field == "created_on" and value is None:
        raise ServiceError({"created_on": "날짜를 선택하세요."})

    # auto_now는 update()를 타지 않으므로 직접 넣는다.
    updated = MeetingNote.objects.filter(pk=note.pk, version=expected_version).update(
        version=expected_version + 1, updated_at=timezone.now(), **{field: value}
    )
    if updated != 1:
        note.refresh_from_db()
        raise ConflictError(note)
    note.refresh_from_db()
    return note


def upload_note(*, org, actor, filename: str, raw: bytes, project=None) -> MeetingNote:
    """.md 본문 텍스트만 읽어 새 회의록을 만든다. 파일은 저장하지 않는다."""
    if not filename.lower().endswith((".md", ".markdown")):
        raise ServiceError({"file": ".md 또는 .markdown 파일만 올릴 수 있습니다."})
    if len(raw) > MAX_BODY:
        raise ServiceError({"file": "파일이 너무 큽니다 (256KB 상한)."})
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ServiceError({"file": "UTF-8로 저장된 파일만 읽을 수 있습니다."}) from None
    title = re.sub(r"\.(md|markdown)$", "", filename, flags=re.I)
    return create_note(org=org, actor=actor, title=title, project=project, body_md=body)


def delete_note(note, actor):
    """작성자 본인이거나 조직 관리자만."""
    if note.created_by_id != actor.pk and not is_admin(actor, note.org):
        raise ServiceError({"note": "작성자나 조직 관리자만 지울 수 있습니다."})
    note.delete()


def link_task(note, task, actor):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if task.project.org_id != note.org_id:
        raise ServiceError({"task": "같은 조직의 태스크여야 합니다."})
    note.tasks.add(task)


def unlink_task(note, task, actor):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    note.tasks.remove(task)
```

**이미지 첨부는 없다.** 파일 저장 경로를 만들지 않는다.

---

## 3. Step 3. 뷰와 URL

```
orgs/<int:org_id>/notes                     org_notes          ?scope=all|team|<project_id>&note=<id>
orgs/<int:org_id>/notes/new                 note_new           POST
orgs/<int:org_id>/notes/upload              note_upload        POST (multipart)
notes/<int:note_id>/save                    note_save          POST
notes/<int:note_id>/delete                  note_delete        POST
tasks/<int:task_id>/notes                   task_note_link     POST
tasks/<int:task_id>/notes/<int:note_id>/unlink   task_note_unlink   POST
```

`web/views/notes.py`. 목록과 편집기가 **한 화면**이다.

```python
@login_required
def org_notes(request, org_id):
    org = org_or_404(request.user, org_id)
    scope = request.GET.get("scope", "all")
    qs = org.notes.select_related("project", "created_by")
    if scope == "team":
        qs = qs.filter(project__isnull=True)
    elif scope.isdecimal():
        qs = qs.filter(project_id=int(scope))
    notes = list(qs)

    raw = request.GET.get("note", "")
    note = next((n for n in notes if str(n.pk) == raw), None) or (notes[0] if notes else None)

    # 프로젝트별 묶음. 팀 공통이 맨 뒤.
    groups, seen = [], {}
    for n in notes:
        key = n.project_id or 0
        if key not in seen:
            seen[key] = {"title": n.project.name if n.project else "팀 공통", "items": []}
            groups.append(seen[key])
        seen[key]["items"].append(n)
    groups.sort(key=lambda g: g["title"] == "팀 공통")
    for g in groups:
        g["hint"] = f"{len(g['items'])}건"

    return render(request, "notes/list.html", {
        "org": org, "tab": "notes", "is_admin": can_admin(request.user, org),
        "groups": groups, "note": note, "scope": scope,
        "projects": org.projects.filter(is_archived=False).order_by("name"),
        "can_delete": bool(note) and (note.created_by_id == request.user.pk or can_admin(request.user, org)),
    })
```

`note_save`는 부분 렌더를 하지 않는다. 204와 헤더만 돌려준다.

```python
@login_required
@require_POST
def note_save(request, note_id):
    note = _note_or_404(request.user, note_id)
    field = request.POST.get("field", "")
    raw = request.POST.get("value", "")
    value = raw
    if field == "project":
        value = project_or_404(request.user, raw) if raw else None
    elif field == "created_on":
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            value = None
    try:
        note = ts_notes.update_note(
            note, field, value, actor=request.user, expected_version=version_of(request)
        )
    except ServiceError as e:
        return HttpResponse(" ".join(e.errors.values()), status=400)
    except ConflictError:
        return HttpResponse(CONFLICT_MSG, status=409)
    resp = HttpResponse(status=204)
    resp["X-Note-Version"] = str(note.version)
    return trigger(resp, "saved")
```

`note_new`·`note_upload`는 만들고 나서 `redirect(f"{reverse('org_notes', args=[org.pk])}?note={note.pk}")`.

`orgs/_tabs.html`에 한 줄 더한다.

```html
  <a href="{% url 'org_notes' org.pk %}" {% if tab == "notes" %}aria-current="page"{% endif %}>회의록</a>
```

---

## 4. Step 4. 템플릿 `notes/list.html`

좌우 두 카드다(`.today-columns`와 같은 flex 규칙을 쓰는 `.notes-columns`).

**왼쪽**

- 헤더: "회의록" + [.md 올리기](`<label>` 안에 숨긴 `<input type="file" accept=".md,.markdown">`, 선택 즉시 `form.requestSubmit()`) + [새 회의록]
- 범위 칩: 전체 / 팀 공통 / 프로젝트마다 하나. 현재 범위는 `aria-pressed="true"`
- 그룹: 헤딩(프로젝트명 또는 "팀 공통") + 건수, 항목마다 제목과 "작성자 · vN · 수정일"
- 선택 항목은 `class="sel"` → `box-shadow: inset 3px 0 0 var(--primary)`
- 카드 아래 안내: "회의록은 프로젝트에 붙일 수도 있고 팀 공통으로 남길 수도 있습니다. 올린 .md는 본문 텍스트만 읽어 저장합니다. 파일 자체와 이미지 첨부는 저장되지 않습니다."

**오른쪽** (회의록이 없으면 "왼쪽에서 회의록을 고르거나 새로 만드세요.")

```html
<section class="card" id="note-editor">
  <input class="title-input" data-note-field="title" value="{{ note.title }}" aria-label="제목">
  <div class="row t13 muted">
    <select class="select auto" data-note-field="project" aria-label="프로젝트">
      <option value="">팀 공통 (프로젝트 없음)</option>
      {% for p in projects %}<option value="{{ p.pk }}"{% if p.pk == note.project_id %} selected{% endif %}>{{ p.name }}</option>{% endfor %}
    </select>
    <span>{{ note.created_by.display_name }}</span>
    <label class="row" style="gap:4px">생성일
      <input class="input auto" type="date" data-note-field="created_on" value="{{ note.created_on|date:'Y-m-d' }}" aria-label="생성일">
    </label>
    <span id="note-status" class="status" aria-live="polite">v{{ note.version }} · {{ note.updated_at|date:"n/j H:i" }}</span>
  </div>
  <div id="note-conflict" class="error" hidden>다른 사람이 먼저 수정했습니다. 새로고침한 뒤 다시 쓰세요.</div>

  <form id="doc-form" method="post" action="{% url 'note_save' note.pk %}">{% csrf_token %}
    <input type="hidden" name="field" value="body_md">
    <input type="hidden" name="version" value="{{ note.version }}">
    <div id="doc" class="doc" data-url="{% url 'note_save' note.pk %}" data-version="{{ note.version }}">
      <div id="doc-body"></div>
      <textarea id="doc-src" name="value" class="textarea" rows="16">{{ note.body_md }}</textarea>
    </div>
    <button id="doc-submit" class="btn sm primary">저장</button>
  </form>

  <div class="row t13 muted" style="border-top:1px solid var(--border);padding-top:8px">
    아무 곳이나 눌러 바로 씁니다. # 제목, - 목록, - [ ] 체크, &gt; 인용, --- 구분선, **굵게**, *기울임*, `코드`. Enter 새 줄, Backspace 합치기, 화살표로 이동. 자동 저장됩니다.
    {% if can_delete %}<form method="post" action="{% url 'note_delete' note.pk %}" onsubmit="return confirm('이 회의록을 지울까요?')">{% csrf_token %}<button class="btn sm danger">삭제</button></form>{% endif %}
  </div>
</section>
```

`#doc-src`와 `#doc-submit`은 **JS가 없을 때를 위한 것**이다. `notes.js`가 뜨면 둘을 숨기고 `#doc-body`를 그린다. 이 순서 덕분에 JS 실패가 편집 불가로 이어지지 않는다.

`base.html`에 `notes.js`를 붙인다. 다른 화면에서는 `#doc`이 없어 즉시 빠져나오므로 조건부 로드가 필요 없다.

```html
<script src="{% static 'notes.js' %}"></script>
```

---

## 5. Step 5. `core/web/static/notes.js` (전체)

```js
// 회의록 인라인 편집기. 서버는 마크다운을 텍스트로만 다루고, 문서를 그리는 것은 여기뿐이다.
// innerHTML을 쓰지 않는다 — 이것이 XSS를 막는 유일한 장치다.
(function () {
  var doc = document.getElementById("doc");
  if (!doc) return;
  var bodyEl = document.getElementById("doc-body");
  var src = document.getElementById("doc-src");
  var submit = document.getElementById("doc-submit");
  var statusEl = document.getElementById("note-status");
  var conflictEl = document.getElementById("note-conflict");
  var csrf = (document.querySelector("#doc-form [name=csrfmiddlewaretoken]") || {}).value || "";

  var lines = src.value.replace(/\r\n/g, "\n").split("\n");
  var version = Number(doc.dataset.version);
  var editing = -1, caret = null, timer = null, dead = false;

  src.hidden = true;
  if (submit) submit.hidden = true;

  // ---------- 파싱 ----------
  function parse(raw) {
    var t = raw.trim(), m;
    if ((m = /^(#{1,3})\s+(.*)$/.exec(t))) return { type: "h", level: m[1].length, text: m[2] };
    if ((m = /^[-*]\s+\[([ xX])\]\s*(.*)$/.exec(t))) return { type: "todo", checked: m[1] !== " ", text: m[2] };
    if ((m = /^(\d+)\.\s+(.*)$/.exec(t))) return { type: "li", marker: m[1] + ".", text: m[2] };
    if (/^[-*]\s+/.test(t)) return { type: "li", marker: "•", text: t.replace(/^[-*]\s+/, "") };
    if (/^>\s?/.test(t)) return { type: "quote", text: t.replace(/^>\s?/, "") };
    if (/^(---|\*\*\*)$/.test(t)) return { type: "rule", text: "" };
    return { type: "p", text: t };
  }

  var INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|~~[^~]+~~)/g;
  function inline(text, parent) {
    var last = 0, m;
    INLINE.lastIndex = 0;
    while ((m = INLINE.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      var tok = m[0], el;
      if (tok.slice(0, 2) === "**") { el = document.createElement("strong"); el.textContent = tok.slice(2, -2); }
      else if (tok.slice(0, 2) === "~~") { el = document.createElement("s"); el.textContent = tok.slice(2, -2); }
      else if (tok.charAt(0) === "`") { el = document.createElement("code"); el.textContent = tok.slice(1, -1); }
      else { el = document.createElement("em"); el.textContent = tok.slice(1, -1); }
      parent.appendChild(el);
      last = m.index + tok.length;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  // ---------- 렌더 ----------
  function autosize(ta) { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; }

  function block(raw, i) {
    var b = parse(raw);
    var wrap = document.createElement("div");
    wrap.className = "blk blk-" + b.type + (b.type === "h" ? " h" + b.level : "");
    if (b.type === "rule") {
      wrap.appendChild(document.createElement("hr"));
    } else if (b.type === "todo") {
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = b.checked;
      cb.setAttribute("aria-label", b.text);
      cb.addEventListener("change", function (e) { e.stopPropagation(); toggle(i); });
      wrap.appendChild(cb);
      var sp = document.createElement("span");
      sp.className = "txt" + (b.checked ? " done" : "");
      inline(b.text, sp);
      wrap.appendChild(sp);
    } else {
      if (b.type === "li") {
        var mk = document.createElement("span");
        mk.className = "mk";
        mk.textContent = b.marker;
        wrap.appendChild(mk);
      }
      var el = document.createElement(
        b.type === "h" ? "h" + b.level : b.type === "quote" ? "blockquote" : "div"
      );
      el.className = "txt";
      inline(b.text, el);
      if (!b.text) el.appendChild(document.createTextNode(" "));
      wrap.appendChild(el);
    }
    wrap.addEventListener("click", function (e) {
      if (e.target && e.target.type === "checkbox") return;
      editing = i; caret = null; render();
    });
    return wrap;
  }

  function editor(raw, i) {
    var ta = document.createElement("textarea");
    ta.className = "blk-edit";
    ta.rows = 1;
    ta.value = raw;
    ta.setAttribute("aria-label", "본문 입력");
    ta.addEventListener("input", function () { lines[i] = ta.value; autosize(ta); save(); });
    ta.addEventListener("keydown", function (e) { keys(e, ta, i); });
    return ta;
  }

  function render() {
    while (bodyEl.firstChild) bodyEl.removeChild(bodyEl.firstChild);
    for (var i = 0; i < lines.length; i++) {
      bodyEl.appendChild(i === editing ? editor(lines[i], i) : block(lines[i], i));
    }
    var ta = bodyEl.querySelector("textarea");
    if (ta) {
      autosize(ta);
      ta.focus();
      var p = caret == null ? ta.value.length : Math.min(caret, ta.value.length);
      ta.setSelectionRange(p, p);
    }
  }

  function changed() { render(); save(); }

  function toggle(i) {
    lines[i] = /\[[xX]\]/.test(lines[i])
      ? lines[i].replace(/\[[xX]\]/, "[ ]")
      : lines[i].replace(/\[ \]/, "[x]");
    changed();
  }

  // ---------- 키 ----------
  function keys(e, ta, i) {
    var at = ta.selectionStart;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      var head = ta.value.slice(0, at), tail = ta.value.slice(at);
      var cont = /^(\s*(?:[-*]\s\[[ xX]\]|[-*]|\d+\.)\s)/.exec(head);
      // 접두어만 남은 줄에서 Enter를 치면 목록을 끝낸다.
      var prefix = cont && tail === "" && head.trim() !== cont[1].trim() ? cont[1] : "";
      lines.splice(i, 1, head, prefix + tail);
      editing = i + 1; caret = prefix.length;
      changed();
    } else if (e.key === "Backspace" && at === 0 && i > 0) {
      e.preventDefault();
      var prev = lines[i - 1];
      lines.splice(i - 1, 2, prev + ta.value);
      editing = i - 1; caret = prev.length;
      changed();
    } else if (e.key === "ArrowUp" && at === 0 && i > 0) {
      e.preventDefault(); editing = i - 1; caret = null; render();
    } else if (e.key === "ArrowDown" && at === ta.value.length && i < lines.length - 1) {
      e.preventDefault(); editing = i + 1; caret = 0; render();
    } else if (e.key === "Escape") {
      e.preventDefault(); editing = -1; render();
    }
  }

  doc.addEventListener("click", function (e) {
    if (e.target !== doc && e.target !== bodyEl) return;   // 빈 영역만
    if (lines.length && lines[lines.length - 1].trim() === "") {
      editing = lines.length - 1;
    } else {
      lines.push("");
      editing = lines.length - 1;
    }
    caret = 0;
    changed();
  });

  // ---------- 저장 ----------
  function flash(text) { if (statusEl) statusEl.textContent = text; }

  function send(field, value) {
    if (dead) return;
    var data = new FormData();
    data.append("field", field);
    data.append("value", value);
    data.append("version", String(version));
    flash("저장 중…");
    fetch(doc.dataset.url, {
      method: "POST", headers: { "X-CSRFToken": csrf }, body: data, credentials: "same-origin",
    }).then(function (r) {
      if (r.status === 409) {
        dead = true;
        if (conflictEl) conflictEl.hidden = false;
        flash("저장하지 못했습니다");
        return;
      }
      if (!r.ok) throw new Error(String(r.status));
      version = Number(r.headers.get("X-Note-Version")) || version + 1;
      doc.dataset.version = String(version);
      flash("자동 저장됨");
    }).catch(function () { flash("저장 실패 · 새로고침하세요"); });
  }

  function save() {
    clearTimeout(timer);
    timer = setTimeout(function () {
      src.value = lines.join("\n");
      send("body_md", src.value);
    }, 800);
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-note-field]"), function (el) {
    el.addEventListener("change", function () { send(el.dataset.noteField, el.value); });
  });

  render();
})();
```

`app.css`:

```css
.notes-columns { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
.notes-columns > .list { flex: 1 1 320px; min-width: 0; }
.notes-columns > .card:last-child { flex: 9999 1 420px; min-width: 0; }
.note-item { display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-surface); text-align: left; cursor: pointer; }
.note-item.sel { box-shadow: inset 3px 0 0 var(--primary); }
.doc { display: flex; flex-direction: column; min-height: 360px; padding: 8px 0; cursor: text; }
.blk { padding: 2px 6px; font-size: 15px; line-height: 24px; display: flex; gap: 8px; align-items: baseline; }
.blk .txt { flex: 1; min-width: 0; }
.blk .mk { flex: none; color: var(--text-secondary); }
.blk-h { display: block; padding-top: 8px; }
.blk-h.h1 .txt { font-size: 26px; line-height: 34px; font-weight: 700; letter-spacing: -0.02em; }
.blk-h.h2 .txt { font-size: 20px; line-height: 28px; font-weight: 700; letter-spacing: -0.02em; }
.blk-h.h3 .txt { font-size: 17px; line-height: 26px; font-weight: 700; letter-spacing: -0.02em; }
.blk-quote .txt { padding-left: 12px; border-left: 3px solid var(--border); color: var(--text-secondary); }
.blk-todo .txt.done { text-decoration: line-through; color: var(--text-secondary); }
.blk code { background: var(--bg-fill); border-radius: 4px; padding: 1px 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.blk hr { width: 100%; border: 0; border-top: 1px solid var(--border); }
.blk-edit { display: block; width: 100%; padding: 2px 6px; border: 0; border-radius: 4px; background: var(--bg-secondary); outline: none; font: inherit; font-size: 15px; line-height: 24px; resize: none; overflow: hidden; color: var(--text-primary); }
```

---

## 6. Step 6. 패널 "참고 자료"

`tasks/_links.html`을 **`tasks/_refs.html`로 바꾼다**(제목 "문서·PR 링크" → "참고 자료").

- **회의록**: `<select>`에 그 조직의 회의록을 담고 [연결]. 목록 항목은 `종류 배지(회의록)` + 제목 버튼(누르면 그 회의록으로 이동) + [✕]
- **외부 주소**: 접힌 `＋ 외부 주소 추가` 안에 제목·URL·종류. 종류는 문서·이슈·대시보드·기타만 보인다
- 안내: "PR·커밋은 저장소 연결이 자동으로 붙입니다. 여기에는 앱 안의 회의록이나 앱이 모르는 외부 주소만 연결합니다."

`web/forms.py`의 `LinkForm`:

```python
    kind = forms.ChoiceField(
        label="종류",
        choices=[(c, label) for c, label in Link.KINDS if c in ("doc", "issue", "dash", "other")],
        initial="doc",
    )
```

`_panel.html`의 `<div id="links">`를 `<div id="refs">`로 바꾸고 include 대상을 `_refs.html`로 바꾼다. `link_add`·`link_delete` 뷰의 부분 렌더 대상도 함께 바꾼다.

---

## 7. 테스트

| 이름 | 확인 |
|---|---|
| `test_note_create_and_list_scopes` | 전체·팀 공통·프로젝트 범위 필터 |
| `test_note_save_bumps_version` | 저장마다 `version` +1, 응답 헤더 `X-Note-Version` |
| `test_note_save_conflict_returns_409` | 낡은 version이면 409 |
| `test_note_project_must_be_same_org` | 다른 조직 프로젝트는 거부 |
| `test_note_title_defaults_when_blank` | 빈 제목은 "제목 없는 회의록" |
| `test_note_body_size_cap` | 256KB 초과는 400 |
| `test_upload_md_only` | `.txt`는 거부, `.md`는 본문만 들어온다 |
| `test_upload_rejects_non_utf8` | 잘못된 인코딩은 400 |
| `test_upload_title_from_filename` | 확장자를 뗀 파일명이 제목 |
| `test_note_delete_author_or_admin` | 남의 회의록을 일반 멤버가 못 지운다 |
| `test_task_note_link_unlink` | 패널에서 연결·해제, 다른 조직 태스크는 거부 |
| `test_link_form_hides_pr_repo` | 폼 선택지에 PR·저장소가 없다 |
| `test_notes_hidden_from_other_org` | 다른 조직 사람은 404 |

`notes.js`는 브라우저에서 손으로 확인한다. 수동 확인 목록에 다음을 넣는다.

1. 줄을 누르면 그 줄만 입력칸이 되고 나머지는 그대로다
2. Enter로 줄이 갈라지고 `- ` 목록 접두어가 이어진다
3. 줄 맨 앞에서 Backspace를 누르면 앞 줄과 합쳐진다
4. ↑↓로 줄을 오간다. Esc로 편집이 끝난다
5. 체크박스를 누르면 원문 `- [ ]`가 `- [x]`로 바뀌고 저장된다
6. 빈 영역을 누르면 마지막에 새 줄이 생긴다
7. 두 창에서 같은 회의록을 열고 양쪽에서 쓰면 뒤늦은 쪽에 충돌 배너가 뜬다
8. JavaScript를 끄면 textarea와 [저장] 버튼으로 편집된다

## 8. 완료 체크

- [ ] `markdown`·`bleach`를 넣지 않았다
- [ ] `notes.js`에 `innerHTML`이 없다(`grep -n innerHTML core/web/static/notes.js`가 비어 있다)
- [ ] 저장이 낙관적 잠금을 지킨다
- [ ] 업로드가 파일을 저장하지 않는다
- [ ] 패널 참고 자료에서 회의록을 연결하고 이동한다
