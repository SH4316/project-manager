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
  // 읽기 전용(거버넌스 보기 등): 같은 파서로 그리기만 하고 편집·저장은 하지 않는다.
  var readonly = doc.dataset.readonly === "1";

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
      if (!b.text) el.appendChild(document.createTextNode(" "));
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
      bodyEl.appendChild(!readonly && i === editing ? editor(lines[i], i) : block(lines[i], i));
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
    if (readonly) return;
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
    if (readonly) return;
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
