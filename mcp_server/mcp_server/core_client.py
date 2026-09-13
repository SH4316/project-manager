import os

import httpx

CORE_URL = os.environ.get("CORE_URL", "http://web:8000").rstrip("/")


class CoreError(Exception):
    pass


class Core:
    def __init__(self, token: str, transport=None):
        self.http = httpx.Client(
            base_url=CORE_URL,
            timeout=20,
            headers={"Authorization": f"Bearer {token}", "X-Source": "mcp"},
            transport=transport,
        )

    def _ok(self, r: httpx.Response):
        if r.status_code == 204:
            return None
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 401:
            raise CoreError("토큰이 유효하지 않습니다. 폐기됐거나 만료됐을 수 있습니다.")
        if r.status_code == 403:
            raise CoreError("이 토큰으로는 할 수 없는 작업입니다(읽기 전용).")
        if r.status_code == 404:
            raise CoreError("대상을 찾을 수 없습니다.")
        if r.status_code == 409:
            latest = r.json().get("latest", {})
            raise CoreError(
                "다른 사용자가 먼저 수정했습니다. 최신 version="
                f"{latest.get('version')} 로 다시 시도하세요. 최신 내용: {latest}"
            )
        if r.status_code in (400, 422):
            raise CoreError(f"입력 오류: {r.json().get('detail')}")
        raise CoreError(f"core 오류 HTTP {r.status_code}")

    def get(self, path, **params):
        return self._ok(
            self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        )

    def post(self, path, body=None, headers=None):
        return self._ok(self.http.post(path, json=body or {}, headers=headers))

    def patch(self, path, body):
        return self._ok(self.http.patch(path, json=body))

    def delete(self, path):
        return self._ok(self.http.delete(path))
