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

    def webhook_urls(self, team_id: int) -> list[str]:
        """웹 화면(팀 → 알림 채널)에 등록된, 켜져 있는 Webhook 주소. 팀 관리자 토큰이 필요하다."""
        r = self.http.get("/api/integrations/discord/webhooks", params={"team": team_id})
        r.raise_for_status()
        return r.json()["urls"]

    def weekly(self, team_id: int, week_start: str) -> dict:
        r = self.http.get("/api/reports/weekly", params={"team": team_id, "week_start": week_start})
        r.raise_for_status()
        return r.json()

    def report_status(self, ok: bool, detail: dict):
        try:
            self.http.post("/api/integrations/discord/status", json={"ok": ok, "detail": detail})
        except httpx.HTTPError:
            pass  # 상태 보고 실패는 본 작업을 막지 않는다
