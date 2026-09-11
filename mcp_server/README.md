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

`<MCP_URL>`은 `https://mcp.<도메인>`, `<TOKEN>`은 core의 `/settings/tokens`에서 발급한 값.

| 클라이언트 | 설정 |
|---|---|
| Claude Code | `claude mcp add --transport http sandol <MCP_URL>/mcp --header "Authorization: Bearer <TOKEN>"` |
| Codex CLI | `~/.codex/config.toml`에 `[mcp_servers.sandol]` `url = "<MCP_URL>/mcp"` `bearer_token_env_var = "SANDOL_TOKEN"` 추가, 환경 변수 `SANDOL_TOKEN=<TOKEN>` |
| Claude 앱 / claude.ai | 설정 → 커넥터 → 커스텀 커넥터 추가 → URL `<MCP_URL>/u/<TOKEN>/mcp`, 인증 없음 |
| ChatGPT | 설정 → 커넥터(개발자 모드) → 추가 → URL `<MCP_URL>/u/<TOKEN>/mcp`, 인증 없음 |

개인 비밀 URL은 비밀번호와 같다. 공유하지 말고, 유출되면 `/settings/tokens`에서 폐기한다.

## 도구 14개

`list_orgs` `list_projects` `get_project` `list_tasks` `get_task` `create_task` `update_task`
`transition_task` `append_note` `get_org_status` `get_weekly_report_data` `list_members`
`search` `fetch` (뒤 두 개는 ChatGPT 커넥터 호환 별칭)

수정 도구는 `get_task`로 읽은 최신 `version`을 함께 보낸다. 충돌하면 다시 읽고 재시도한다.

## 테스트

```bash
uv run pytest -q
uv run ruff check .
```
