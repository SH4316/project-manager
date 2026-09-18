# mcp_server

산돌이 태스크를 AI 클라이언트(Claude Code, Codex CLI, Claude 앱, ChatGPT)에 연결하는 MCP 서버.
core 코드를 import하지 않는다. core의 HTTP API만 호출하는 얇은 껍데기이고 상태를 두지 않는다.

## 환경 변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `CORE_URL` | `http://web:8000` | core 주소 |
| `PORT` | `8080` | 수신 포트 |

토큰은 요청마다 온다. `Authorization: Bearer <TOKEN>` 헤더나 경로 `/u/<TOKEN>/mcp` 중 하나를 쓴다.

## 실행

```bash
CORE_URL=http://localhost:8000 uv run python -m mcp_server
```

## 클라이언트 연결

운영 서버의 MCP 주소는 `https://mcp.sio2.kr`이다(다른 곳에 올렸다면 그 주소로 바꿔 읽는다). `<TOKEN>`은 core의 `/settings/tokens`에서 발급한 값.

| 클라이언트 | 설정 |
|---|---|
| Claude Code | `claude mcp add --transport http sandol https://mcp.sio2.kr/mcp --header "Authorization: Bearer <TOKEN>"` |
| Codex CLI | `~/.codex/config.toml`에 `[mcp_servers.sandol]` `url = "https://mcp.sio2.kr/mcp"` `bearer_token_env_var = "SANDOL_TOKEN"` 추가, 환경 변수 `SANDOL_TOKEN=<TOKEN>` |
| Claude 앱 / claude.ai | 설정 → 커넥터 → 커스텀 커넥터 추가 → URL `https://mcp.sio2.kr/u/<TOKEN>/mcp`, 인증 없음 |
| ChatGPT | 설정 → 커넥터(개발자 모드) → 추가 → URL `https://mcp.sio2.kr/u/<TOKEN>/mcp`, 인증 없음 |

개인 비밀 URL은 비밀번호와 같다. 공유하지 말고, 유출되면 `/settings/tokens`에서 폐기한다.

## 도구 20개

- 태스크·프로젝트: `list_orgs` `list_projects` `get_project` `list_tasks` `get_task`
  `create_task` `update_task` `transition_task` `append_note`
- 거버넌스: `get_governance` — 그 조직의 개발 규칙(마크다운). **쓰기 전에 먼저 읽는다.**
- 팀: `list_teams` `create_team` `add_team_member` `remove_team_member` `set_project_teams`
- 현황: `get_org_status` `get_weekly_report_data` `list_members`
- ChatGPT 커넥터 호환 별칭: `search` `fetch`

수정 도구는 `get_task`로 읽은 최신 `version`을 함께 보낸다. 충돌하면 다시 읽고 재시도한다.
거버넌스는 조직이 화면에서 고치는 글이고 서버는 검증하지 않는다 — 자세한 건 `docs/GOVERNANCE.md`.

## 테스트

```bash
uv run pytest -q
uv run ruff check .
```
