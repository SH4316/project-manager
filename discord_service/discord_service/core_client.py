import httpx


class CoreClient:
    def __init__(self, base_url: str, token: str, transport=None):
        self.http = httpx.Client(
            base_url=base_url,
            timeout=20,
            headers={"Authorization": f"Bearer {token}", "X-Source": "api"},
            transport=transport,
        )

    def open_tasks(self, team_id: int, due_to: str | None = None) -> list[dict]:
        """미완료 태스크 전부 (페이지 순회). due_to는 'YYYY-MM-DD'."""
        items, offset = [], 0
        while True:
            params = {
                "team": team_id,
                "status": "todo,doing,paused,blocked,review",
                "limit": 200,
                "offset": offset,
            }
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

    # --- 봇 명령 (행위자는 연결된 사람. core가 discord_user_id로 찾는다) ---

    def _bot(self, path: str, body: dict) -> dict:
        r = self.http.post(f"/api/integrations/discord{path}", json=body)
        r.raise_for_status()
        return r.json()

    def link(self, code: str, did: str) -> dict:
        return self._bot("/link", {"code": code, "discord_user_id": did})

    def unlink(self, did: str) -> dict:
        return self._bot("/unlink", {"discord_user_id": did})

    def today(self, did: str) -> dict:
        return self._bot("/today", {"discord_user_id": did})

    def done(self, did: str, task_id: int) -> dict:
        return self._bot(f"/tasks/{task_id}/done", {"discord_user_id": did})

    def extend(self, did: str, task_id: int, due_date: str, reason: str) -> dict:
        return self._bot(
            f"/tasks/{task_id}/extend",
            {"discord_user_id": did, "due_date": due_date, "reason": reason},
        )

    def report_status(self, ok: bool, detail: dict):
        try:
            self.http.post("/api/integrations/discord/status", json={"ok": ok, "detail": detail})
        except httpx.HTTPError:
            pass  # 상태 보고 실패는 본 작업을 막지 않는다
