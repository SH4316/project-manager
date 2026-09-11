# 구현 완료 보고서 2: 조직·팀 재구성과 GitHub 통합

작성일: 2026-09-12
범위: [GUIDE-V2-00](GUIDE-V2-00-overview.md) ~ [GUIDE-V2-08](GUIDE-V2-08-github-write.md) 여덟 단계 전부
브랜치: `claude/project-manager-implementation-plan-1f668d`
이전 라운드 보고서: [IMPL-REPORT.md](IMPL-REPORT.md) (2026-09-10, core 145개)

**이것이 v1이다.** [IMPL-PLAN-2.md](IMPL-PLAN-2.md) §3의 완료 조건을 전부 닫았다.

---

## 1. 요약

| 파트 | SQLite | Postgres 16 | ruff |
|---|---|---|---|
| `core/` | **306 passed**, skip 0 | **306 passed**, skip 0 | 0 |
| `discord_service/` | **58 passed** | (DB 미사용) | 0 |
| `mcp_server/` | **16 passed** | (DB 미사용) | 0 |

`makemigrations --check --dry-run` → "No changes detected".
core 테스트가 145 → 306으로 늘었다(+161).

단계별로 지시서 하나씩 끝냈고, 단계마다 위 검증을 전부 통과한 뒤 다음으로 갔다.

| 단계 | 내용 | 끝난 뒤 core 테스트 |
|---|---|---|
| 1 | `teams` 앱 → `orgs`, 조직·팀·멤버 3계층, 마이그레이션 초기화 | 158 |
| 2 | 헤더 5영역, 조직·프로젝트 하위 탭, 접이식 레일, 조직 → 팀 화면 | 169 |
| 3 | 칸반 드래그, 월 캘린더(시간표 삭제) | 182 |
| 4 | 부하 현황, 스킬 태그, `Milestone`·`ProjectDependency` | (4·5 합쳐) 210 |
| 5 | `notes` 앱, 인라인 편집기, 태스크 참조 | |
| 6 | `ApiSpec`, 서버 프록시, 태그별 렌더 | 230 |
| 7 | GitHub App 설치·계정 연결·권한 필터·웹훅·자동 전환 5규칙 | 274 |
| 8 | 조직 초대, 팀 동기화, 이슈·브랜치 만들기 | 306 |

---

## 2. 실제 환경에서 확인한 것

개발 서버를 공개 도메인 뒤에 두고 인터넷에서 확인했다.

| 확인 | 결과 |
|---|---|
| `https://project.dorm.sio2.kr/healthz` | 200 `{"ok": true}` |
| TLS·프록시 헤더 | Let's Encrypt 정상, `Set-Cookie ... Secure` (Django가 `X-Forwarded-Proto`를 읽는다) |
| GitHub App JWT | 실제 키로 `GET /app` 성공. 권한 5종 확인, **Administration 없음** |
| 웹훅 서명 | 올바른 서명 202 · 틀린 서명 **401** · 서명 없음 **401** |
| 웹훅 자동 전환 | `create`(브랜치 `feat/TASK-1-e2e`) → 태스크 시작 전 **→ 진행 중**, `TaskGitLink.branch` 저장, 이력에 `external_actor` |
| Discord 봇 | 게이트웨이 접속(`ProjectManager#3181`), 채널 발송 200, 마감 스캔이 `GET /api/tasks?org=1` 200 |
| MCP | `list_orgs`·`get_org_status` 호출 성공. 숫자가 웹 화면과 일치 |
| A18 모바일 | 375×812에서 행 상태 컨트롤로 완료 → `completed_at` 기록, 이력 `review → done / web` |

확인용으로 만든 것(가짜 저장소 연결, MCP 스모크 토큰)은 전부 지웠다.
`[데모]` 접두가 붙은 조직 데이터는 화면 확인용으로 남겨 뒀다 — 지워도 된다.

---

## 3. 지시서를 고친 곳

구현하다 지시서 자체의 버그를 넷 찾았다. 코드는 고친 쪽으로 갔다.

| 자리 | 문제 | 고친 것 |
|---|---|---|
| `notes/models.py` | `MeetingNote.tasks`의 `related_name="notes"`가 `Task.notes`(진행 메모 필드)와 충돌 → `fields.E302`로 `makemigrations`가 즉시 실패 | `related_name="meeting_notes"` |
| `notes/services.py` | `create_note(created_on=created_on or None)`이 모델의 `default=today_kst`를 명시적 `None`으로 덮어써 NOT NULL 위반 | `or today_kst()` |
| `github/services.py` | 이슈 자동 가져오기가 `due_date`도 `no_due_reason`도 없이 `create_task`를 불러 `_validate`가 거부 → **웹훅이 항상 400** | `no_due_reason="GitHub 이슈로 가져옴"` |
| `projects/services.py` | `fetch_spec`이 스킴·크기·시간만 막고 호스트를 안 봄. 지시서가 "사내 주소까지 막아야 하면 나중에"로 남겨 둠 | 아래 §4 |

`docs/IMPL-REPORT.md`의 검수 시나리오 A01 매핑이 개명 전 테스트 이름을 가리키고 있어 현재 이름으로 고쳤다
(테스트 자체는 `team` → `org`로 이름만 바뀐 채 살아 있다. 커버리지 손실 없음).

---

## 4. SSRF를 막았다

`fetch_spec`은 사용자가 준 주소를 **서버가 대신** 받아 온다. 받아 온 내용은 화면에 그대로 나온다.
이 배포는 같은 도커 망에 `web:8000`·`mcp:8080`·`db:5432`가 있어서, 막지 않으면 조직 멤버 누구나
이 서버를 발판 삼아 내부를 읽을 수 있었다.

주소를 풀어 사설·루프백·링크로컬·예약 IP를 거부하고, 리다이렉트가 내부로 되돌리는 경로도
`HTTPRedirectHandler`에서 다시 검사한다. 컨테이너 안에서 확인했다.

```
blocked http://web:8000/api/openapi.json
blocked http://127.0.0.1:8000/api/openapi.json
blocked http://db:5432/
blocked http://169.254.169.254/latest/meta-data/   (클라우드 메타데이터)
blocked file:///etc/passwd
```

DNS 리바인딩은 남아 있다(주소를 풀고 연결하기까지의 틈). 막으려면 IP로 직접 붙고 `Host` 헤더를
세우는 방식으로 바꿔야 한다. 코드에 `# ponytail:` 주석으로 한계를 적어 뒀다.

---

## 5. 보안 경계와 그것을 고정한 테스트

틀리면 조용히 뚫리는 자리들이다. 전부 테스트로 못 박았다.

### 웹훅 (`core/github/tests.py`)

| 고정한 것 | 왜 |
|---|---|
| 서명이 틀리면 401, `GitEvent` 안 생김 | |
| **비밀이 비어 있으면 전부 거부** | 지시서가 정하지 않은 자리. 열어 두면 인증 없는 공개 쓰기 경로가 된다 |
| 세션 쿠키·API 토큰으로 못 들어옴 | 이 경로의 인증은 서명 하나뿐이어야 한다 |
| 같은 초에 70건을 보내도 429 없음 | 전역 분당 60건 한도에 묶이면 push가 몰릴 때 이벤트를 잃는다 |
| `hmac.compare_digest` 사용 | `==`는 비교 시간이 내용에 따라 달라진다 |
| JWT가 실제 RS256 서명 | 공개키로 검증한다 |

### 토큰 (`core/github/tests.py`)

- 설치 토큰은 **읽기 전용**. 쓰는 곳이 GET뿐인지 확인.
- 사용자 토큰은 Fernet 암호화 저장. 키를 갈면 예외가 아니라 빈 문자열(로그인이 막히지 않게).
- 만료되면 refresh로 갱신하고, refresh도 죽었으면 "다시 연결하세요".
- `sync_repos`가 **자기 조직의 설치만** 묻는다(남의 조직 설치는 건드리지 않는다).

### 쓰기 (`core/github/test_writes.py`)

| 고정한 것 | 왜 |
|---|---|
| 모든 쓰기가 **누른 사람 토큰**으로 나감 | 기록이 그 사람 이름으로 남고, 그가 GitHub에서 못 하는 일은 GitHub가 거부한다 |
| `writes.py`에 `installation_token`이 **코드로** 없음(AST로 검사) | 설치 토큰은 읽기 전용 |
| `teams/*/repos` 호출 없음 | 저장소 권한 부여 API는 Administration 쓰기를 요구하고, 거기엔 저장소 삭제가 딸려 온다 |
| `DELETE .../teams/` 없음 | PM 팀을 지워도 GitHub 팀은 남긴다. PM이 모르는 저장소 권한이 붙어 있을 수 있다 |
| GitHub가 403이어도 PM 변경이 살아남음 | 되돌리기 애매한 절반 성공을 만들지 않는다 |
| 브랜치 이름이 공백·`..`·끝 슬래시를 거부 | 경로 조작 |

### 가시성

- 태스크는 조직 규칙으로, **GitHub에서 온 데이터는 GitHub 권한으로** 본다.
- `can_view_repo()` 한 곳을 화면 전부가 지난다. `repo_state()`가 `none`·`unlinked`·`denied`·`ok` 넷을 돌려주고 화면 문구가 상태마다 고정이다.
- `actor=None`은 웹훅 경로에서만 쓴다. `git grep`으로 `github/` 밖에 없음을 고정했다.
- 회의록 렌더러(`notes.js`)에 `innerHTML`이 없다. `createElement`·`textContent`만 쓴다.

---

## 6. 목업 대조

19건의 차이를 찾았고 **결함은 없다.** 셋으로 갈린다.

- **조직·팀 재구성으로 늘어난 것**: 상단 "조직" 탭, 조직 → 팀 화면 전체, 조직 개요의 "담당 팀" 열.
- **GitHub App 통합으로 재설계된 것**: 목업의 "연동 키" 화면(PAT 입력·배포 키 표)이 "설치 상태 + 내 GitHub 연결 + 저장소 연결 현황"으로 바뀌었다. PAT 입력 제거는 [GUIDE-V2-00](GUIDE-V2-00-overview.md) §4의 의도된 v1 제외 항목이다.
- **문구 축약 등 표시 차이**: "팀 부하 현황" → "부하 현황" 등.

재확인이 필요해 보였던 셋은 전부 의도된 것으로 확인됐다.

| 지적 | 확인 결과 |
|---|---|
| 부하 현황에 기간 선택(이번 주/이번 달)이 없다 | [IMPL-PLAN-2](IMPL-PLAN-2.md) §2가 이 화면 요소를 "스킬 태그, **팀별 필터**, 마일스톤, 의존성"으로 정했다. 기간은 로드맵의 3개월 창에만 쓴다 |
| 행 버튼이 "오늘 추가"가 아니라 "자동 추가 · 오늘 제외" | 마감 기준 자동 담기(`TodayItem.excluded`)가 이전 라운드에 확정된 동작이다. 이미 담긴 태스크에는 "제외"가 맞다 |
| "제외 N건 · 복원" 문구가 안 보인다 | `today/_list.html`이 `counts.excluded > 0`일 때만 그린다. 현재 제외가 0건이라 숨은 것 |

목업은 이 두 계획보다 먼저 그려진 판이라 따라오지 못한 자리들이다.

---

## 7. 검수 시나리오

SPEC §12의 A01~A14·A18과 GUIDE 표의 B01~B05가 전부 대응 테스트를 갖고 있다.
매핑 표는 [IMPL-REPORT.md](IMPL-REPORT.md) '검수 시나리오 대응' 절에 있고, 이번에 이름을 현행화했다.
A18(모바일 완료)만 수동 항목이며 §2에서 직접 확인했다.

---

## 8. v1에서 일부러 뺀 것

[GUIDE-V2-00](GUIDE-V2-00-overview.md) §4 목록이 그대로 지켜지는지 `git grep`으로 확인했다. 전부 없다.

PR 병합 · PM에서 커밋 · 저장소 생성·삭제 · 브랜치 보호 규칙 · 배포 키 · PAT 입력 화면 ·
개인에게 저장소 권한 부여 · 팀에 저장소 권한 부여.

그 밖에 만들지 않은 것: 회의록 버전 이력 화면과 이미지 첨부, 마일스톤에 태스크 연결,
로드맵 기간 전환, PR 리뷰 승인 수, 부하 계산의 중요도 가중치, 조직 초대 시 팀 자동 배정.

---

## 9. 배포 전에 해야 하는 것

**이 셋은 코드로 해결되지 않는다.**

1. **GitHub 앱을 조직에 설치한다.** 현재 `installations: 0`이다. PM 화면(조직 → GitHub → [GitHub 앱 설치])에서 해야 한다 — GitHub 앱 페이지의 Install을 직접 누르면 PM이 어느 조직에 붙일지 모른다. 그 뒤 각자 프로필에서 [GitHub 연결]을 한다.
2. **`admin` 비밀번호를 바꾼다.** 개발용으로 `admin`/`admin`이고 서버가 인터넷에 열려 있다.
   `docker compose exec web python manage.py changepassword admin`
3. **방화벽에서 8000번을 리버스 프록시 장비 IP에만 연다.** `compose.yml`의 `web`이 `0.0.0.0:8000`으로 열려 있고 gunicorn이 `--forwarded-allow-ips="*"`라, 그 포트에 닿는 누구든 `X-Forwarded-Proto`를 위조할 수 있다.

배포 절차 자체는 [GUIDE-04](GUIDE-04-deploy.md)에서 바뀌지 않았다.
`.env`에 GitHub App 설정 6개와 `CREDENTIAL_KEY`가 늘었을 뿐이다.
`CREDENTIAL_KEY`는 **한 번 정하면 바꾸지 않는다** — 갈면 저장된 사용자 토큰을 전부 못 읽어
모두가 GitHub를 다시 연결해야 한다.

---

## 10. 남은 한계

코드에 `# ponytail:` 주석으로 표시해 둔 것들이다. 지금 규모에서는 문제가 없고, 넘어서면 그때 바꾼다.

| 자리 | 한계 | 넘어설 때 |
|---|---|---|
| `client.installation_token` | 프로세스별 메모리 캐시. gunicorn 워커마다 따로 받는다 | 워커가 많아지면 DB·캐시 백엔드로 |
| `fetch_spec` | DNS 리바인딩 | IP로 직접 붙고 `Host` 헤더를 세운다 |
| `sync_issues` | 열린 이슈 첫 100건 | 페이지를 돈다 |
| `TaskGitLink.commits` | 최근 100건 JSON 목록 | 별도 표로 |
| `GitEvent` | 연결당 50건에서 잘린다 | 감사 로그가 필요하면 보관 정책으로 |
| `refresh_github_access` | 요청 경로에서 6시간에 한 번 GitHub를 부른다 | 느껴지면 GitHub 화면 첫 진입으로 미룬다 |

---

## 11. 작업 방식

지시서 한 단계를 한 에이전트가 끝까지 들고 가게 했다. services/api/web/템플릿으로 쪼개면
같은 지시서를 여러 번 읽게 되고 버그가 그 이음매에서 난다.

- **탐색·문서 읽기**는 Haiku가 먼저 "어느 파일 어느 줄"을 뽑아 구현 프롬프트에 박아 넣었다.
- **일반 구현**은 Sonnet. 4·5단계는 병렬로 돌렸다(4는 `projects` 앱, 5는 새 `notes` 앱이라
  마이그레이션이 겹치지 않는다). 6단계는 4와 같은 앱을 건드려서 뒤로 미뤘다.
- **보안에 직결되는 것**(Fernet·JWT·웹훅 HMAC·권한 필터·`actor=None` 경계·모든 쓰기 경로)과
  **최종 검증**은 넘기지 않았다.

병렬로 돌릴 때는 공유 파일(`web/urls.py`, `orgs/_tabs.html`, `app.css`)에 각자 표시한 블록으로만
덧붙이고 기존 줄은 건드리지 않게 했다. 그 제약 때문에 `app.css`에 `.bar` 규칙이 중복으로 남았고
나중에 정리했다.
