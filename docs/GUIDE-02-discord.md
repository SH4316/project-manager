# 구현 지시서 02: discord_service (별도 프로세스)

GUIDE-00을 먼저 읽는다. 이 파트는 **core 코드를 한 줄도 import하지 않는다.** core와는 HTTP API(GUIDE-01-3)로만 통신한다. 의존성은 `httpx` 하나. 상태는 SQLite 파일 하나. Django 없음.

역할: 마감 알림(D-3, D-1, 당일, 기한 초과)과 주간 보고를 Discord Webhook으로 보낸다. 결과를 core에 보고한다.

개정 2026-09-10: 태스크 상태 7개(`paused`·`blocked`가 상태), `is_blocked` 대신 `status`·`stop_reason`, 주간 집계에서 `commented` 삭제.

---

## Step 0. 환경

`discord_service/` 디렉터리에서:

```bash
uv init --no-workspace --name sandol-discord --python 3.12
uv add "httpx>=0.27"
uv add --dev "pytest>=8" "ruff>=0.6"
```

자동 생성된 `main.py`/`hello.py`는 지운다. `pyproject.toml`에 추가:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]
```

파일 구성:

```
discord_service/
  pyproject.toml
  Dockerfile
  README.md
  discord_service/
    __init__.py
    __main__.py     CLI: run | once | test | weekly | status
    config.py       환경 변수 → Config
    store.py        SQLite
    core_client.py  core API 호출
    discord.py      Webhook 전송 (재시도, 2000자 분할)
    messages.py     메시지 문자열 만들기
    notify.py       마감 알림 작업
    weekly.py       주간 보고 작업
    summarize.py    요약 (LLM 자리, 기본 고정 형식)
    scheduler.py    60초 루프
  tests/
    conftest.py  test_notify.py  test_weekly.py  test_discord.py  test_store.py
```

---

## Step 1. 설정과 저장소

### `discord_service/config.py`

```python
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    core_url: str
    core_token: str
    team_id: int
    webhook_url: str
    tz: ZoneInfo
    send_hour: int
    weekly_weekday: int
    weekly_hour: int
    llm_provider: str
    db_path: str
    site_name: str

    @classmethod
    def from_env(cls) -> "Config":
        def need(k):
            v = os.environ.get(k, "").strip()
            if not v:
                raise SystemExit(f"환경 변수 {k} 가 필요합니다.")
            return v

        return cls(
            core_url=need("CORE_URL").rstrip("/"),
            core_token=need("CORE_TOKEN"),
            team_id=int(need("TEAM_ID")),
            webhook_url=need("DISCORD_WEBHOOK_URL"),
            tz=ZoneInfo(os.environ.get("TZ", "Asia/Seoul")),
            send_hour=int(os.environ.get("SEND_HOUR", "9")),
            weekly_weekday=int(os.environ.get("WEEKLY_WEEKDAY", "0")),
            weekly_hour=int(os.environ.get("WEEKLY_HOUR", "9")),
            llm_provider=os.environ.get("LLM_PROVIDER", "").strip().lower(),
            db_path=os.environ.get("DB_PATH", "/data/discord.sqlite"),
            site_name=os.environ.get("SITE_NAME", "산돌이 업무"),
        )
```

### `discord_service/store.py`

```python
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

DDL = """
CREATE TABLE IF NOT EXISTS sent(
  task_id INTEGER NOT NULL, kind TEXT NOT NULL, due_date TEXT NOT NULL,
  status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
  created_at TEXT NOT NULL, sent_at TEXT,
  PRIMARY KEY(task_id, kind, due_date)
);
CREATE TABLE IF NOT EXISTS daily(kind TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY(kind, date));
CREATE TABLE IF NOT EXISTS weekly(
  period_start TEXT PRIMARY KEY, data_json TEXT NOT NULL, summary TEXT NOT NULL,
  source TEXT NOT NULL, sent_status TEXT NOT NULL, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ran_at TEXT NOT NULL,
  ok INTEGER NOT NULL, note TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            c.executescript(DDL)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- 마감 알림 ---
    def claim(self, task_id: int, kind: str, due_date: str) -> bool:
        """발송 전에 자리를 잡는다. 이미 있으면 False (중복 방지)."""
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO sent(task_id, kind, due_date, status, created_at) VALUES(?,?,?,?,?)",
                (task_id, kind, due_date, "sending", _now()),
            )
            return cur.rowcount == 1

    def mark(self, task_id: int, kind: str, due_date: str, status: str, error: str | None = None):
        with self._conn() as c:
            c.execute(
                "UPDATE sent SET status=?, attempts=attempts+1, last_error=?, sent_at=? WHERE task_id=? AND kind=? AND due_date=?",
                (status, error, _now() if status == "sent" else None, task_id, kind, due_date),
            )

    def release(self, task_id: int, kind: str, due_date: str):
        """발송하지 않기로 했을 때(완료·기한 변경) 자리를 지운다."""
        with self._conn() as c:
            c.execute("DELETE FROM sent WHERE task_id=? AND kind=? AND due_date=? AND status='sending'", (task_id, kind, due_date))

    # --- 하루 1회 작업 ---
    def claim_daily(self, kind: str, date: str) -> bool:
        with self._conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO daily(kind, date) VALUES(?,?)", (kind, date))
            return cur.rowcount == 1

    def release_daily(self, kind: str, date: str):
        with self._conn() as c:
            c.execute("DELETE FROM daily WHERE kind=? AND date=?", (kind, date))

    # --- 주간 ---
    def weekly_sent(self, period_start: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT sent_status FROM weekly WHERE period_start=?", (period_start,)).fetchone()
            return row is not None and row["sent_status"] == "sent"

    def save_weekly(self, period_start: str, data_json: str, summary: str, source: str, sent_status: str):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO weekly(period_start, data_json, summary, source, sent_status, sent_at) VALUES(?,?,?,?,?,?)",
                (period_start, data_json, summary, source, sent_status, _now() if sent_status == "sent" else None),
            )

    # --- 실행 기록 ---
    def record_run(self, name: str, ok: bool, note: str = ""):
        with self._conn() as c:
            c.execute("INSERT INTO runs(name, ran_at, ok, note) VALUES(?,?,?,?)", (name, _now(), int(ok), note[:500]))

    def recent(self, limit: int = 20) -> dict:
        with self._conn() as c:
            runs = [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
            sent = [dict(r) for r in c.execute("SELECT * FROM sent ORDER BY created_at DESC LIMIT ?", (limit,))]
            weekly = [dict(r) for r in c.execute("SELECT period_start, source, sent_status, sent_at FROM weekly ORDER BY period_start DESC LIMIT 5")]
        return {"runs": runs, "sent": sent, "weekly": weekly}
```

---

## Step 2. core 클라이언트와 Webhook

### `discord_service/core_client.py`

```python
import httpx


class CoreClient:
    def __init__(self, base_url: str, token: str, transport=None):
        self.http = httpx.Client(
            base_url=base_url, timeout=20,
            headers={"Authorization": f"Bearer {token}", "X-Source": "api"},
            transport=transport,
        )

    def open_tasks(self, team_id: int, due_to: str | None = None) -> list[dict]:
        """미완료 태스크 전부 (페이지 순회). due_to는 'YYYY-MM-DD'."""
        items, offset = [], 0
        while True:
            params = {"team": team_id, "status": "todo,doing,paused,blocked,review", "limit": 200, "offset": offset}
            if due_to:
                params["due_to"] = due_to
            r = self.http.get("/api/tasks", params=params)
            r.raise_for_status()
            data = r.json()
            items.extend(data["items"])
            offset += data["limit"]
            if offset >= data["total"]:
                return items

    def task(self, task_id: int) -> dict | None:
        r = self.http.get(f"/api/tasks/{task_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def weekly(self, team_id: int, week_start: str) -> dict:
        r = self.http.get("/api/reports/weekly", params={"team": team_id, "week_start": week_start})
        r.raise_for_status()
        return r.json()

    def report_status(self, ok: bool, detail: dict):
        try:
            self.http.post("/api/integrations/discord/status", json={"ok": ok, "detail": detail})
        except httpx.HTTPError:
            pass  # 상태 보고 실패는 본 작업을 막지 않는다
```

### `discord_service/discord.py`

```python
import time

import httpx

MAX_LEN = 1900  # Discord content 한도 2000자, 여유


def chunk(text: str) -> list[str]:
    """줄 단위로 1900자 이하 조각으로 나눈다."""
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > MAX_LEN and buf:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts or [""]


class Webhook:
    def __init__(self, url: str, transport=None, sleep=time.sleep):
        self.url = url
        self.http = httpx.Client(timeout=15, transport=transport)
        self.sleep = sleep

    def send(self, text: str) -> str:
        """'sent' | 'unknown' 를 돌려주거나, 3회 실패 시 예외를 던진다."""
        for part in chunk(text):
            self._send_one(part)
        return "sent"

    def _send_one(self, content: str):
        delay = 2.0
        last = None
        for _ in range(3):
            try:
                r = self.http.post(self.url, json={"content": content, "allowed_mentions": {"parse": ["users"]}})
            except httpx.TimeoutException as e:
                raise UnknownResult(str(e)) from e
            except httpx.HTTPError as e:
                last = e
                self.sleep(delay)
                delay *= 2
                continue
            if r.status_code in (200, 204):
                return
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = float(r.headers.get("Retry-After", delay))
                last = RuntimeError(f"HTTP {r.status_code}")
                self.sleep(max(retry_after, delay))
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise RuntimeError(f"3회 실패: {last}")


class UnknownResult(Exception):
    """응답을 못 받아 성공 여부를 모른다."""
```

`allowed_mentions.parse=["users"]`는 사용자 멘션만 허용하고 `@everyone`·역할 멘션을 막는다.

---

## Step 3. 메시지와 마감 알림

### `discord_service/messages.py`

```python
STATUS = {
    "todo": "시작 전", "doing": "진행 중", "paused": "일시정지", "blocked": "막힘",
    "review": "검토 대기", "done": "완료", "cancelled": "취소",
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
    lines = [task_line(t) + (f"  (기한 {t['due_date']})" if kind == "overdue" else "") for t in tasks]
    return head + "\n" + "\n".join(lines)


def test_message(site_name: str) -> str:
    return f"✅ {site_name} Discord 알림 연결 테스트"
```

### `discord_service/notify.py`

```python
import logging
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import UnknownResult, Webhook
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


def run_deadlines(core: CoreClient, hook: Webhook, store: Store, team_id: int, today: date) -> dict:
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
            fresh = core.task(t["id"])  # 발송 직전 재확인 (A09, A10)
            if fresh is None or classify(fresh, today) != kind or fresh["due_date"] != t["due_date"]:
                store.release(t["id"], kind, t["due_date"])
                result["skipped"] += 1
                continue
            _send(hook, store, deadline_message(kind, [fresh], today_s), t["id"], kind, t["due_date"], result)

    # 기한 초과: 하루 1건 묶음
    if per_kind["overdue"]:
        if store.claim_daily("overdue", today_s):
            fresh_list = []
            for t in per_kind["overdue"]:
                fresh = core.task(t["id"])
                if fresh and classify(fresh, today) == "overdue":
                    fresh_list.append(fresh)
            if fresh_list:
                fresh_list.sort(key=lambda x: (x["due_date"], x["id"]))
                _send(hook, store, deadline_message("overdue", fresh_list, today_s), 0, "overdue", today_s, result)
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
```

규칙 정리:

- D-3·D-1·당일은 **그 날에만** 보낸다. `classify`가 정확히 3, 1, 0일 차이만 잡으므로 하루 지나면 자동으로 안 보낸다(소급 금지).
- 기한이 바뀌면 `(task_id, kind, due_date)` 키가 달라지므로 새 기한 기준으로 다시 보내고, 옛 기한 기준은 재확인에서 걸러진다.
- 완료·취소된 태스크는 `open_tasks` 조회와 재확인 두 번 걸러진다.
- 막힘·일시정지 태스크도 미완료이므로 포함한다. 메시지에는 상태 뒤에 사유가 괄호로 붙는다.
- `failed`로 남은 건은 재시도하지 않는다. `# ponytail: 실패 건 자동 재시도 없음, 필요하면 status='failed' 행을 다음날 재시도`

---

## Step 4. 주간 보고

### `discord_service/summarize.py`

```python
from .messages import STATUS, mention


def fixed_summary(data: dict) -> str:
    """LLM 없이 만드는 고정 형식 보고서."""
    c = data["counts"]
    head = f"📊 주간 업데이트 · {data['team']['name']} · {data['period_start']} ~ {data['period_end']} (직전 주)"
    quiet = c["completed"] == 0 and c["reopened"] == 0 and c["overdue"] == 0 and c["blocked"] == 0 and c["due_this_week"] == 0
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
        head, "",
        section("지난주 완료", data["completed"]),
        section("지난주 재개", data["reopened"]),
        section("이번 주 마감", data["due_this_week"], lambda t: f" — {t['due_date']}"),
        section("기한 초과", data["overdue"], lambda t: f" — 기한 {t['due_date']}"),
        section("막힘", data["blocked"]),
    ]
    proj = [f"• {p['project']['name']}: 완료 {p['completed']} · 미완료 {p['open']} · 초과 {p['overdue']} · 막힘 {p['blocked']}" for p in data["by_project"]]
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
```

### `discord_service/weekly.py`

```python
import json
import logging
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import UnknownResult, Webhook
from .store import Store
from .summarize import summarize

log = logging.getLogger(__name__)


def last_monday(today: date) -> date:
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def run_weekly(core: CoreClient, hook: Webhook, store: Store, team_id: int, week_start: date, provider: str, force: bool = False) -> dict:
    ws = week_start.isoformat()
    if not force and store.weekly_sent(ws):
        return {"status": "skipped", "period_start": ws}
    data = core.weekly(team_id, ws)
    summary, source = summarize(data, provider)
    try:
        hook.send(summary)
        status = "sent"
    except UnknownResult:
        status = "unknown"
    except Exception as e:  # noqa: BLE001
        log.error("주간 보고 발송 실패: %s", e)
        status = "failed"
    store.save_weekly(ws, json.dumps(data, ensure_ascii=False), summary, source, status)
    return {"status": status, "period_start": ws, "source": source}
```

---

## Step 5. 스케줄러와 CLI

### `discord_service/scheduler.py`

```python
import logging
import time
from datetime import datetime

from .config import Config
from .core_client import CoreClient
from .discord import Webhook
from .notify import run_deadlines
from .store import Store
from .weekly import last_monday, run_weekly

log = logging.getLogger(__name__)


def tick(cfg: Config, core: CoreClient, hook: Webhook, store: Store, now: datetime) -> list[dict]:
    """1분마다 호출. 실행한 작업 결과 목록."""
    results = []
    today = now.date()
    if now.hour >= cfg.send_hour and store.claim_daily("deadline", today.isoformat()):
        try:
            r = run_deadlines(core, hook, store, cfg.team_id, today)
            store.record_run("deadline", True, str(r))
            core.report_status(True, {"job": "deadline", **r})
            results.append({"job": "deadline", **r})
        except Exception as e:  # noqa: BLE001
            store.release_daily("deadline", today.isoformat())  # 다음 tick에 다시 시도
            store.record_run("deadline", False, str(e))
            core.report_status(False, {"job": "deadline", "error": str(e)})
            log.exception("deadline job failed")
    if now.weekday() == cfg.weekly_weekday and now.hour >= cfg.weekly_hour:
        ws = last_monday(today)
        if not store.weekly_sent(ws.isoformat()):
            try:
                r = run_weekly(core, hook, store, cfg.team_id, ws, cfg.llm_provider)
                store.record_run("weekly", r["status"] == "sent", str(r))
                core.report_status(r["status"] == "sent", {"job": "weekly", **r})
                results.append({"job": "weekly", **r})
            except Exception as e:  # noqa: BLE001
                store.record_run("weekly", False, str(e))
                core.report_status(False, {"job": "weekly", "error": str(e)})
                log.exception("weekly job failed")
    return results


def loop(cfg: Config):
    # ponytail: 단일 프로세스 전제. 복제 수를 늘리면 SQLite 파일을 공유하지 못하므로 1개만 띄운다.
    core = CoreClient(cfg.core_url, cfg.core_token)
    hook = Webhook(cfg.webhook_url)
    store = Store(cfg.db_path)
    log.info("discord_service 시작 (team=%s, send_hour=%s)", cfg.team_id, cfg.send_hour)
    while True:
        try:
            tick(cfg, core, hook, store, datetime.now(cfg.tz))
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        time.sleep(60)
```

`send_hour` **이후** 첫 tick에 보내는 방식이다(`>=`). 서비스가 9시 이후에 켜져도 그날 알림을 한 번은 보낸다. 다만 하루 넘긴 D-3·D-1은 `classify`가 걸러 소급 발송하지 않는다.

### `discord_service/__main__.py`

```python
import argparse
import json
import logging
from datetime import date, datetime

from .config import Config
from .core_client import CoreClient
from .discord import Webhook
from .messages import test_message
from .notify import run_deadlines
from .scheduler import loop, tick
from .store import Store
from .weekly import last_monday, run_weekly


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="discord_service")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="60초 루프로 상주")
    sub.add_parser("once", help="지금 시각 기준 tick 1회")
    sub.add_parser("test", help="테스트 메시지 1건")
    w = sub.add_parser("weekly", help="주간 보고")
    w.add_argument("--now", action="store_true", help="이미 보냈어도 다시 보낸다")
    w.add_argument("--week-start", help="YYYY-MM-DD (월요일)")
    d = sub.add_parser("deadlines", help="마감 알림 즉시 실행")
    d.add_argument("--date", help="YYYY-MM-DD 기준일 (기본 오늘)")
    sub.add_parser("status", help="최근 발송 기록")
    a = p.parse_args()

    cfg = Config.from_env()
    store = Store(cfg.db_path)
    core = CoreClient(cfg.core_url, cfg.core_token)
    hook = Webhook(cfg.webhook_url)

    if a.cmd == "run":
        loop(cfg)
    elif a.cmd == "once":
        print(tick(cfg, core, hook, store, datetime.now(cfg.tz)))
    elif a.cmd == "test":
        hook.send(test_message(cfg.site_name))
        print("sent")
    elif a.cmd == "weekly":
        ws = date.fromisoformat(a.week_start) if a.week_start else last_monday(datetime.now(cfg.tz).date())
        print(run_weekly(core, hook, store, cfg.team_id, ws, cfg.llm_provider, force=a.now))
    elif a.cmd == "deadlines":
        today = date.fromisoformat(a.date) if a.date else datetime.now(cfg.tz).date()
        print(run_deadlines(core, hook, store, cfg.team_id, today))
    elif a.cmd == "status":
        print(json.dumps(store.recent(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

`discord_service/__init__.py`는 빈 파일.

---

## Step 6. 테스트

### `tests/conftest.py`

```python
import json

import httpx
import pytest

from discord_service.core_client import CoreClient
from discord_service.discord import Webhook
from discord_service.store import Store


OPEN = ("todo", "doing", "paused", "blocked", "review")


def task(i, due, status="todo", stop_reason=""):
    return {
        "id": i, "number": f"TASK-{i}", "title": f"할 일 {i}",
        "project": {"id": 1, "name": "학식 API", "team_id": 1},
        "assignee": {"id": 2, "display_name": "팀원", "discord_user_id": "111"},
        "status": status, "priority": 5, "due_date": due, "stop_reason": stop_reason,
        "next_action": "", "url": f"http://pm/tasks/{i}",
    }


class FakeCore:
    """core API 흉내. tasks dict를 바꾸면 응답이 바뀐다."""

    def __init__(self, tasks: list[dict], weekly: dict | None = None):
        self.tasks = {t["id"]: t for t in tasks}
        self.weekly_data = weekly
        self.status_reports = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/tasks":
            items = [t for t in self.tasks.values() if t["status"] in OPEN]
            due_to = request.url.params.get("due_to")
            if due_to:
                items = [t for t in items if t["due_date"] and t["due_date"] <= due_to]
            return httpx.Response(200, json={"items": items, "total": len(items), "limit": 200, "offset": 0})
        if path.startswith("/api/tasks/"):
            t = self.tasks.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=t) if t else httpx.Response(404, json={"detail": "x"})
        if path == "/api/reports/weekly":
            return httpx.Response(200, json=self.weekly_data)
        if path.startswith("/api/integrations/"):
            self.status_reports.append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404)


class FakeHook:
    def __init__(self, statuses=None):
        self.sent = []
        self.statuses = list(statuses or [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(json.loads(request.content)["content"])
        code = self.statuses.pop(0) if self.statuses else 204
        return httpx.Response(code, headers={"Retry-After": "0"} if code == 429 else {})


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.sqlite"))


@pytest.fixture
def fake_hook():
    return FakeHook()


@pytest.fixture
def hook(fake_hook):
    return Webhook("https://discord.com/api/webhooks/x/y", transport=httpx.MockTransport(fake_hook.handler), sleep=lambda s: None)


def make_core(fake: FakeCore) -> CoreClient:
    return CoreClient("http://core", "pm_test", transport=httpx.MockTransport(fake.handler))
```

### 테스트 목록

`tests/test_notify.py`

| 테스트 | 검증 |
|---|---|
| `test_classify` | 오늘 2026-09-09 기준 due 09-12→`d3`, 09-10→`d1`, 09-09→`d0`, 09-01→`overdue`, 09-11→None, None→None, status done→None |
| `test_sends_each_kind_once` | task d3·d1·d0 각 1개 + overdue 2개 → `run_deadlines` 결과 `sent == 4` (개별 3 + 묶음 1), `fake_hook.sent` 4건, overdue 메시지에 두 태스크 번호 모두 포함. 같은 날 다시 실행 → `sent == 0`, `skipped >= 4` (A11) |
| `test_due_changed_before_send_not_sent` | 첫 `open_tasks` 응답 뒤 재확인 시 `due_date`가 바뀌도록: `FakeCore.tasks[id]["due_date"]`를 목록 조회 후 바꾸는 트릭 대신, `core.task`가 다른 값을 돌려주도록 `FakeCore` 인스턴스의 dict를 테스트 중간에 수정하는 것은 불가능하므로 **`CoreClient.task`를 monkeypatch**해 다른 `due_date`를 돌려준다 → `sent == 0`, `skipped == 1`, `store`에 `sending` 행이 남지 않는다 (A09) |
| `test_completed_before_send_not_sent` | `CoreClient.task`를 monkeypatch해 `status="done"` 반환 → `sent == 0` (A10) |
| `test_blocked_task_included` | `status="blocked", stop_reason="서류 대기"`인 d0 태스크 → 발송되고 메시지에 "막힘"과 "서류 대기" 포함. `status="paused"`인 d1 태스크도 발송된다 |
| `test_no_backfill_for_missed_days` | due가 오늘+2인 태스크(어제였다면 d3) → 아무것도 안 보냄 |
| `test_failed_send_recorded` | `FakeHook(statuses=[500,500,500])` → `failed == 1`, `store.recent()["sent"][0]["status"] == "failed"` |
| `test_retry_on_429_then_success` | `FakeHook(statuses=[429, 204])` → `sent == 1`, hook 호출 2회 |
| `test_status_reported_to_core` | `tick` 실행 후 `fake_core.status_reports[-1]["ok"] is True` |

`tests/test_weekly.py`

| 테스트 | 검증 |
|---|---|
| `test_fixed_summary_quiet` | counts 전부 0 → "특이 사항 없음" 포함 |
| `test_fixed_summary_sections` | completed 1, overdue 1 → "지난주 완료", "기한 초과", 태스크 번호, `<@111>` 포함 |
| `test_summarize_falls_back_when_provider_fails` | `provider="bogus"` → source `"fixed"` (A12) |
| `test_run_weekly_once_per_period` | 첫 실행 `status=="sent"`, 두 번째 `"skipped"`, `force=True`면 다시 `"sent"` |
| `test_run_weekly_marks_failed_but_saves` | hook 3회 500 → `status=="failed"`, `store.recent()["weekly"][0]["sent_status"]=="failed"` |
| `test_last_monday` | 2026-09-09(수) → 2026-08-31 |

`tests/test_discord.py`

| 테스트 | 검증 |
|---|---|
| `test_chunk_splits_long_text` | 3000자(줄 100개) → 조각 2개 이상, 각 ≤1900, 이어 붙이면 원문 |
| `test_no_everyone_mentions` | 전송 payload의 `allowed_mentions == {"parse": ["users"]}` |

`tests/test_store.py`

| 테스트 | 검증 |
|---|---|
| `test_claim_is_exclusive` | 같은 키 `claim` 두 번 → True, False |
| `test_release_only_sending` | mark sent 후 release → 행 유지 |
| `test_claim_daily` | 같은 날 두 번 → True, False. release 후 다시 True |

주간 보고용 `weekly` fixture 데이터는 GUIDE-01-2 4.1의 `weekly()` 반환 구조를 그대로 흉내 낸 dict를 conftest에 만들어 쓴다(최상위 키 11개 전부, `counts` 키 8개, 리스트에는 `task()` 헬퍼 결과).

---

## Step 7. Dockerfile과 README

`discord_service/Dockerfile`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY discord_service ./discord_service
ENV PATH="/app/.venv/bin:$PATH" TZ=Asia/Seoul PYTHONUNBUFFERED=1
VOLUME ["/data"]
CMD ["python", "-m", "discord_service", "run"]
```

`discord_service/README.md`에는 환경 변수 표(Step 1의 `Config` 필드 전부, 기본값, 설명), CLI 5개 사용법, "core에 연동 계정을 만들고 팀에 넣은 뒤 읽기 토큰을 발급해 `CORE_TOKEN`으로 쓴다"는 절차, 로컬 실행 예(`CORE_URL=http://localhost:8000 ... uv run python -m discord_service test`)를 적는다.

---

## 검증과 완료 체크

```bash
uv run pytest -q
uv run ruff check .
```

- [ ] 위 두 명령 통과
- [ ] core를 로컬에서 띄우고, 연동 계정 읽기 토큰으로 `uv run python -m discord_service test`가 실제 채널에 메시지를 보낸다
- [ ] `deadlines --date <D-3인 날짜>`로 실제 알림 1건 발송 확인, 같은 명령 재실행 시 `skipped`
- [ ] `weekly --now`로 고정 형식 주간 보고 1건 발송
- [ ] core `/ops`에 `discord` 행이 생긴다
- [ ] `docker build` 성공
- [ ] core 코드를 import한 곳이 없다 (`grep -r "from core\|import django" discord_service/` 결과 없음)
- [ ] 완료 보고서 작성

커밋: `discord_service: notifications and weekly report`

다음: [GUIDE-03-mcp.md](GUIDE-03-mcp.md)
