// 산돌이 태스크 — 표시 보조만. 상태와 규칙은 서버에 있다.
(function () {
  var body = document.body;
  var t1, t2;

  function flash(text, after) {
    var el = document.getElementById("save-status");
    if (!el) return;
    clearTimeout(t1); clearTimeout(t2);
    el.textContent = text;
    if (after) t1 = setTimeout(function () { el.textContent = after; }, 400);
    t2 = setTimeout(function () { el.textContent = ""; }, 2500);
  }

  function openPanel(url, pushUrl) {
    htmx.ajax("GET", url, { target: "#panel", swap: "innerHTML" });
    if (pushUrl) history.pushState(null, "", pushUrl);
  }

  // 프로젝트 레일 접기. 아이콘 열(56px)과 목록(200px)을 오간다.
  function applyRail() {
    var rail = document.querySelector("[data-rail]");
    if (!rail) return;
    var off = localStorage.getItem("rail-collapsed") === "1";
    rail.classList.toggle("collapsed", off);
    var b = rail.querySelector("[data-action='toggle-rail']");
    if (b) {
      b.textContent = off ? "»" : "«";
      b.setAttribute("aria-expanded", off ? "false" : "true");
      b.setAttribute("aria-label", off ? "프로젝트 목록 펼치기" : "프로젝트 목록 접기");
    }
  }
  applyRail();

  // 자동 저장 상태 표시
  body.addEventListener("htmx:beforeRequest", function (e) {
    if (e.target.hasAttribute && e.target.hasAttribute("data-autosave")) flash("저장 중…");
  });
  body.addEventListener("saved", function () { flash("자동 저장됨"); });
  body.addEventListener("htmx:responseError", function (e) {
    alert("저장하지 못했습니다. 페이지를 새로고침한 뒤 다시 시도하세요. (" + e.detail.xhr.status + ")");
  });

  // 행 전체 클릭 → 패널. 행 안의 컨트롤은 제외.
  body.addEventListener("click", function (e) {
    var row = e.target.closest(".task-row");
    if (!row || e.target.closest("button, select, a, input, textarea, form")) return;
    openPanel(row.dataset.panel, "/tasks/" + row.dataset.id);
  });
  body.addEventListener("keydown", function (e) {
    if (!e.target.classList || !e.target.classList.contains("task-row")) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.target.click(); }
  });

  // 링크 복사
  body.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var id = b.dataset.copy, url = location.origin + "/tasks/" + id;
    var done = function () { flash("TASK-" + id + " 링크 복사됨"); };
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
      .then(done, function () { prompt("링크를 복사하세요", url); done(); });
  });

  // 상태 select에서 '막힘' 선택 → 보내지 않고 패널의 사유 박스를 연다. (HTMX는 hx-trigger 필터로 이미 막혀 있다)
  body.addEventListener("change", function (e) {
    var s = e.target;
    if (!s.matches || !s.matches("select[data-status]")) return;
    if (s.value === "blocked" && s.dataset.status !== "blocked") {
      openPanel(s.dataset.panel + "?block=1", "/tasks/" + s.dataset.id);
      s.value = s.dataset.status;
    }
  });

  // 패널·다이얼로그 스왑 후 처리
  body.addEventListener("htmx:afterSwap", function (e) {
    var layout = document.querySelector(".layout");
    if (e.target.id === "panel" && layout) {
      var open = e.target.children.length > 0;
      layout.classList.toggle("has-panel", open);
      layout.classList.toggle("wide", open && localStorage.getItem("panel-wide") === "1");
      var w = e.target.querySelector("[data-action='toggle-wide']");
      if (w) w.textContent = layout.classList.contains("wide") ? "작게 보기" : "크게 보기";
      var f = e.target.querySelector("[data-focus]");
      if (f) f.focus();
    }
    if (e.target.id === "dialog" && e.target.children.length) e.target.showModal();
  });

  // data-action 버튼
  body.addEventListener("click", function (e) {
    var b = e.target.closest("[data-action]");
    if (!b) return;
    var layout = document.querySelector(".layout"), panel = document.getElementById("panel"), dlg = document.getElementById("dialog");
    var a = b.dataset.action;
    if (a === "close-panel") {
      panel.innerHTML = ""; layout.classList.remove("has-panel", "wide");
      history.replaceState(null, "", body.dataset.pageUrl || "/today");
    } else if (a === "toggle-wide") {
      var on = !layout.classList.contains("wide");
      layout.classList.toggle("wide", on); localStorage.setItem("panel-wide", on ? "1" : "0");
      b.textContent = on ? "작게 보기" : "크게 보기";
    } else if (a === "close-dialog") {
      dlg.close(); dlg.innerHTML = "";
    } else if (a === "toggle") {
      var el = document.querySelector(b.dataset.target);
      el.hidden = !el.hidden;
      if (b.dataset.alt) { var t = b.textContent; b.textContent = b.dataset.alt; b.dataset.alt = t; }
      if (!el.hidden) { var i = el.querySelector("input:not([type=hidden]), textarea"); if (i) i.focus(); }
    } else if (a === "toggle-rail") {
      localStorage.setItem("rail-collapsed", localStorage.getItem("rail-collapsed") === "1" ? "0" : "1");
      applyRail();
    }
  });
  var dlg = document.getElementById("dialog");
  if (dlg) dlg.addEventListener("click", function (e) { if (e.target === dlg) { dlg.close(); dlg.innerHTML = ""; } });

  // #task-N 해시로 진입하면 패널을 연다 (생성 직후 리다이렉트, 공유 링크 호환)
  function openHash() {
    var m = /#task-(\d+)/.exec(location.hash);
    if (m) openPanel("/tasks/" + m[1] + "/panel", null);
  }
  openHash();
  window.addEventListener("hashchange", openHash);

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
})();
