# 구현 완료 보고서

작성일: 2026-09-10
범위: [GUIDE-00](GUIDE-00-rules.md) ~ [GUIDE-04](GUIDE-04-deploy.md) 전부 (core Step 0~7, discord_service, mcp_server, 배포 산출물)
브랜치: `claude/project-folder-docs-impl-c997ff`

## 요약

| 파트 | 테스트 | ruff check | ruff format |
|---|---|---|---|
| `core/` | **105 passed**, skip 0 | 0 | 통과 |
| `discord_service/` | **20 passed**, skip 0 | 0 | 통과 |
| `mcp_server/` | **16 passed**, skip 0 | 0 | 통과 |

`/api/docs`에 [GUIDE-01-3](GUIDE-01-core-3-api.md) 5.7 표의 엔드포인트 20개가 모두 보인다.
MCP 서버 ↔ 실제 core E2E(헤더 인증·URL 토큰·도구 14개·`append_note`·이력 경로 `mcp`·폐기 토큰 오류)를 확인했다.

---

## Step 별 보고

### Step 0~1. 저장소·환경·설정 (`step 1: django skeleton, settings, accounts.User`)

- 만든 파일: `core/pyproject.toml`, `core/config/settings.py`, `core/config/urls.py`,
  `core/common/{__init__,logging,errors,dates}.py`, `core/accounts/models.py`,
  `core/api/api.py`(임시), `core/web/urls.py`(임시), 앱 7개 골격
- 검증: `uv run python -c "import django; print(django.get_version())"` → `5.2.17`.
  `makemigrations accounts` → `migrate` → `check` 모두 오류 0. `/admin/` 로그인 화면 확인.
- 지시서와 다르게 한 것: `uv init`이 패키지형 프로젝트(`src/`, `[build-system]`)를 만들어 `uv add`가 실패했다.
  `pyproject.toml`을 애플리케이션형(빌드 백엔드 없음)으로 다시 쓰고 `src/`를 지웠다.
- 실패하거나 못 한 것: 없음

### Step 2. 데이터 모델과 admin (`step 2: models and admin`)

- 만든 파일: `teams/models.py`, `projects/models.py`, `tasks/models.py`, `api/models.py`,
  `{accounts,teams,projects,tasks,api}/admin.py`, 마이그레이션 5개
- 검증: `makemigrations` → `migrate` → `check` 오류 0.
  DB 제약 4개를 shell에서 확인: `status=doing`+기한 없음, `status=blocked`+사유 없음,
  `priority=11`, `status=done`+`completed_at` 없음 → 모두 `IntegrityError`.
- 지시서와 다르게 한 것: `startapp`이 만든 빈 스텁 중 쓰지 않는 것(`reports/models.py`, `web/models.py`,
  `reports/admin.py`, `web/admin.py`, `web/views.py`)을 지웠다. 남겨 두면 `ruff check`가 미사용 import로 잡는다.
- 실패하거나 못 한 것: 없음

### Step 3~4. 서비스 계층·리포트 (`step 3: services layer`)

- 만든 파일: `teams/services.py`, `projects/services.py`, `tasks/services.py`, `tasks/brief.py`,
  `reports/services.py`
- 검증: `manage.py check` 오류 0, `ruff check` 0.
  지시서 3.5의 shell 스크립트 출력이 기대와 같다 → `1`, `TASK-1 done 4 True True`.
- 지시서와 다르게 한 것: 없음 (`ruff format` 결과만 반영)
- 실패하거나 못 한 것: 없음. Step 4는 Step 3 커밋에 함께 들어갔다.

### Step 5. HTTP API (`step 5: http api`)

- 만든 파일: `api/{auth,context,schemas,serialize,api}.py`,
  `api/routers/{__init__,me,teams,projects,tasks,today,reports,integrations}.py`
- 검증: `check` 0, `ruff` 0. OpenAPI 경로 20개가 5.7 표와 일치.
- 지시서와 다르게 한 것: **2건** (아래 "지시서 수정 목록" 1·2번)
- 실패하거나 못 한 것: 없음

### Step 6. 웹 화면 (`step 6: web ui`)

- 만든 파일: `web/static/vendor/htmx.min.js`(2.0.4 다운로드), `web/static/app.css`, `web/static/app.js`,
  `web/urls.py`, `web/forms.py`, `web/context.py`, `web/templatetags/rows.py`,
  `web/views/{common,auth,today,me,teams,projects,tasks,search,settings,ops}.py`,
  템플릿 27개(`base.html`, `today*`, `me.html`, `teams/*`, `projects/*`, `tasks/*`, `auth/*`,
  `settings/*`, `search.html`, `ops.html`)
- 검증: `check` 0, `ruff` 0. 스모크 스크립트로 GET 41개·POST 13개 전부 200/204.
  브라우저에서 §6.10 목록을 실제로 확인했다 (아래 "수동 확인 결과").
- 지시서와 다르게 한 것: **3건** (3·4·5번)
- 실패하거나 못 한 것: 없음

### Step 7. 테스트 (`step 7: tests`)

- 만든 파일: `core/conftest.py`, `{teams,projects,tasks,reports,api,web}/tests.py`
- 검증: `uv run pytest -q` → **105 passed**, skip 0. `ruff check`·`ruff format --check` 통과.
- 지시서와 다르게 한 것: 지시서 7.6 목록에 없는 테스트 2개를 추가했다
  (`test_bearer_write_passes_csrf`, `test_session_write_still_needs_csrf`).
  아래 2번 수정이 회귀하지 않게 막는 테스트다.
- 실패하거나 못 한 것: **Postgres 실행 미확인** (아래 "남은 것" 참고). SQLite에서는 전부 통과.

### discord_service (`discord_service: notifications and weekly report`)

- 만든 파일: `pyproject.toml`, `Dockerfile`, `README.md`,
  `discord_service/{__init__,__main__,config,store,core_client,discord,messages,notify,weekly,summarize,scheduler}.py`,
  `tests/{conftest,test_notify,test_weekly,test_discord,test_store}.py`
- 검증: `uv run pytest -q` → **20 passed**. `ruff check` 0.
  `grep -r "from core\|import django" discord_service/` 결과 없음(core 미의존 확인).
- 지시서와 다르게 한 것: **2건** (7·8번)
- 실패하거나 못 한 것: 실제 Discord 채널 발송(`test`/`deadlines`/`weekly`)은 Webhook URL이 필요해 하지 못했다.

### mcp_server (`mcp_server: tools and auth`)

- 만든 파일: `pyproject.toml`, `Dockerfile`, `README.md`,
  `mcp_server/{__init__,__main__,auth,core_client,server,app}.py`,
  `tests/{conftest,test_auth,test_tools}.py`
- 검증: `uv run pytest -q` → **16 passed**. `ruff check` 0. core 미의존 확인.
  **실제 core를 띄운 상태로 E2E 확인**:
  1. 헤더 인증 `initialize` → 200, 서버 이름 `sandol-pm`
  2. `tools/call list_teams` → 실제 팀 데이터 반환
  3. URL 토큰 경로 `/u/<TOKEN>/mcp` → `tools/list` 도구 **14개**
  4. `append_note` → 기존 메모 뒤에 줄 추가
  5. `transition_task` 뒤 core 변경 이력의 `source == "mcp"` (A05)
  6. 폐기·오류 토큰 → "토큰이 유효하지 않습니다" (A14)
- 지시서와 다르게 한 것: **1건** (6번)
- 실패하거나 못 한 것: Claude Code·Codex CLI·커넥터 등록은 사용자 계정·공개 URL이 필요해 하지 못했다.

### 배포 (`deploy: compose, cloudflared, readme`)

- 만든 파일: `core/Dockerfile`, `core/entrypoint.sh`, `core/.dockerignore`, `compose.yml`,
  `.env.example`, `.gitattributes`, `README.md`의 실행 안내 절
- 지시서와 다르게 한 것: **2건** (9·10번)
- 실패하거나 못 한 것: **`docker compose build`·Postgres 테스트·Proxmox 배포 미실행** (아래).

---

## 지시서 수정 목록

지시서 코드를 그대로 옮겼을 때 동작하지 않아 고친 것들이다. 고친 이유와 범위를 함께 적는다.

1. **`api/routers/today.py` 라우트 순서** — `/order`, `/settings`를 `/{task_id}`보다 **먼저** 등록했다.
   django-ninja는 `{task_id}`에 Django `int` 변환기를 붙이지 않아 `/api/today/order`가 `DELETE /{task_id}`에
   먼저 잡혀 **405**가 났다. 지시서 5.6도 "고정 경로를 먼저 등록한다"고 적고 있어 그 의도대로 맞췄다.
   (지시서가 전제한 "`task_id`는 int 변환기" 부분만 사실과 다르다.)

2. **`api/auth.py` 세션 인증** — `django_auth`를 `BrowserSessionAuth`(세션 쿠키가 있을 때만 동작)로 바꿨다.
   django-ninja의 `SessionAuth`는 쿠키를 읽기 **전에** CSRF를 검사하고 실패하면 403을 던진다. 인증 목록
   첫 번째라서 쿠키가 없는 Bearer 요청(MCP·Discord)의 모든 쓰기가 `{"detail": "CSRF check Failed"}` 403으로
   막혔다. Django 테스트 클라이언트는 기본적으로 CSRF를 강제하지 않아 테스트에서는 드러나지 않았다.
   쿠키가 없으면 곧바로 `TokenAuth`로 넘기고, 쿠키가 있으면 CSRF 검사는 그대로 둔다(브라우저 보호 유지).
   회귀 테스트 2개를 `api/tests.py`에 추가했다.

3. **`web/forms.py` `ProjectForm.name`을 `required=False`로** — 지시서 7.7의
   `test_project_dialog_and_create`는 이름 없이 제출했을 때 **"이름을 입력하세요"**(services 메시지)를
   기대하는데, 폼이 필수면 Django 기본 문구가 나온다. 업무 규칙은 services에만 둔다는 GUIDE-00 §3과도 맞다.

4. **`settings/tokens.html` 앞자리 표시에서 `pm_` 제외** (`{{ t.prefix|slice:"3:" }}…`) — 지시서 7.7의
   `test_token_shown_once`는 두 번째 GET 본문에 `pm_`이 없어야 한다고 요구한다. 토큰 원문은 발급 직후
   1회만 보이고, 목록에는 접두사를 뺀 앞자리만 남는다.

5. **`projects/detail.html`의 `<div id="task-form">` 래퍼 제거** — 래퍼와 그 안의 `<form id="task-form">`이
   같은 id를 써서 HTML이 중복 id가 되고, `data-action="toggle"`이 바깥 div만 토글해 폼이 계속 숨겨져 있었다.
   include만 남겨 id가 폼 하나에만 있게 했다.

6. **`mcp_server` 의존성 `mcp>=1.10` → `mcp>=1.10,<2`** — mcp 2.x에서 `FastMCP`가 `MCPServer`로 개명되어
   지시서 코드가 import부터 실패한다. 지시서 코드를 그대로 쓰기 위해 v1로 고정했다.

7. **`discord_service`·`mcp_server` pytest에 `pythonpath = ["."]` 추가** — 두 패키지를 설치하지 않는 구성이라
   `tests/`에서 `import discord_service`가 실패했다.

8. **`discord_service` 테스트의 시간대** — `ZoneInfo("Asia/Seoul")` 대신 고정 오프셋(`UTC+9`)을 쓴다.
   Windows에는 IANA tzdata가 없고 허용 의존성 표에 `tzdata`가 없다. **운영 코드(`config.py`)는 그대로**이며,
   Docker 이미지(`python:3.12-slim`)에는 tzdata가 있다. 이 제약을 `discord_service/README.md`에 적었다.

9. **`.gitattributes` 추가** — Windows 체크아웃에서 `core/entrypoint.sh`가 CRLF로 바뀌면 컨테이너가 뜨지 않는다.
   `*.sh`, `Dockerfile`을 LF로 고정했다.

10. **`.claude/launch.json`에 `core` 항목 추가** — 목업(`mockup`, 8765)과 개발 서버(8000)를 나란히 띄워
    비교하기 위해서다. 기존 `mockup` 항목은 그대로 뒀다.

11. **사소** — `tests/test_discord.py`의 긴 문자열이 정확히 3000자라 `len(text) > 3000`이 실패했다.
    줄 길이를 늘려 조건을 만족시켰다(검증 내용은 그대로).

12. **이 보고서 파일** — `docs/IMPL-REPORT.md`는 GUIDE-00 §6의 파일 목록에 없다. 완료 보고를 남기라는
    §1.7·§7 요구를 충족하려고 만들었다.

---

## 수동 확인 결과 (GUIDE-01-4 §6.10)

브라우저(개발 서버 `http://127.0.0.1:8000`)에서 직접 확인했다.

| # | 항목 | 결과 |
|---|---|---|
| 1~3 | 가입 → 초대 링크 → 참여 | 통과 (`web/tests.py`, `teams/tests.py`가 같은 경로를 검증) |
| 4 | 빠른 추가 → 오늘 목록·지금 할 일 카드 | 통과 |
| 5 | 자동 담기 / 오늘 제외 / 복원 / 끄기 | 통과 ("마감 3일 이내 자동 추가 3건." 문구 확인) |
| 6 | 행 상태 변경이 행만 갱신 | 통과 |
| 7 | 기한 없는 태스크를 진행 중으로 → 안내 문구 | 통과 (services·web 테스트) |
| 8 | 막힘 선택 → 패널 사유 박스 → 빈 값 오류 → 확정 | 통과 ("막힘 사유를 입력하세요." → 저장 후 pill·사유 표시) |
| 9 | 행 클릭 → 패널, 주소 `/tasks/N`, 크게 보기/닫기 | 통과 |
| 10 | 자동 저장 "저장 중…" → "자동 저장됨", `version` 불변 | 통과 (version 3 → 3) |
| 11 | 목표일 연장: 앞 날짜 거부·사유 필수·이력 note | 통과 (이력 `기한: 9월 11일 → 9월 16일 (연장: 승인 지연)`) |
| 12 | 체크리스트·링크 추가, 링크 복사 | 통과 |
| 13 | 낙관적 잠금 충돌 문구 | 통과 ("먼저 수정했습니다") |
| 14 | `/me` 그룹·필터·팀 전체 읽기 전용 | 통과 (묶음 버튼이 hidden `group`을 덮어씀도 확인) |
| 15 | `/team` 지표 6개·프로젝트 표·새 프로젝트 모달 | 통과 |
| 16 | `/projects/N` 인라인 폼·모달·목록/보드 | 통과 |
| 17 | `/search` 번호·제목·프로젝트 이름 | 통과 |
| 18 | 일정 카드(시간표/캘린더, 마감 ●n) | 통과 |
| 19 | 1150px 이하 패널 전용, 700px 이하 메뉴 두 줄·레일 가로 스크롤·지표 2열 | 통과 |
| 20 | 토큰 1회 표시, `/ops`, `/ops/export.json`, 로그인 리다이렉트 | 통과 |

## 검수 시나리오 대응

A01 A03 A04 A05 A06 A07 A09 A10 A11 A12 A13 A14, B01~B05 에 대응하는 테스트가 있다
(`teams/tests.py`, `tasks/tests.py`, `api/tests.py`, `discord_service/tests/*`, MCP E2E).

---

## 남은 것 (환경 때문에 못 한 것)

**Docker 엔진이 이 환경에서 뜨지 않아** 아래 세 가지를 실행하지 못했다.
Docker Desktop 프로세스는 떠 있지만 `docker-desktop` WSL 배포판이 응답하지 않아 모든 `docker` 명령이 멈춘다
(수동 시작·재시도 모두 실패). Docker Desktop을 정상 기동한 뒤 아래를 그대로 실행하면 된다.

```bash
# 1) Postgres에서 core 테스트
docker compose up -d db
cd core && DATABASE_URL=postgres://pm:pm@localhost:5432/pm uv run pytest -q

# 2) 이미지 3개 빌드
docker compose build web discord mcp

# 3) 로컬 기동 확인
cp .env.example .env   # DEBUG=1, ALLOWED_HOSTS=localhost,127.0.0.1, SITE_URL=http://localhost:8000
docker compose up -d --build db web mcp
docker compose exec web python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/healthz').read())"
```

SQLite 전용 코드는 쓰지 않았고(모델 제약·집계 모두 표준 Django), `psycopg[binary]`와
`dj_database_url`은 이미 설정에 들어가 있다.

사용자 자산이 있어야 하는 것들도 남아 있다. GUIDE-04 Step 5~8 그대로 진행하면 된다.

- 실제 Discord 채널 발송 (`DISCORD_WEBHOOK_URL` 필요) — `python -m discord_service test`
- Cloudflare Tunnel 토큰과 공개 호스트 2개 등록
- Proxmox LXC 생성·배포, UptimeRobot 모니터, vzdump 예약
- Claude Code / Codex CLI / Claude 앱 / ChatGPT 커넥터 등록 (개인 토큰과 공개 MCP URL 필요)
