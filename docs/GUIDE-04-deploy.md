# 구현 지시서 04: 배포 (Proxmox + Docker Compose + Cloudflare Tunnel)

GUIDE-00을 먼저 읽는다. 이 문서는 저장소 루트의 `compose.yml`, `.env.example`, `README.md`, core의 Dockerfile을 만들고 Proxmox에 올리는 절차다. Discord·MCP의 Dockerfile은 각 GUIDE에서 이미 만들었다.

서버는 어떤 포트도 외부에 열지 않는다. Cloudflare Tunnel(`cloudflared` 컨테이너)이 바깥에서 들어오는 HTTPS를 내부 컨테이너로 넘긴다. TLS는 Cloudflare가 끝낸다.

---

## Step 1. core Dockerfile과 entrypoint

`core/Dockerfile`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings
RUN chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```

`core/entrypoint.sh`:

```sh
#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 --workers 2 --timeout 60 \
  --forwarded-allow-ips="*" --access-logfile - --error-logfile -
```

`core/.dockerignore`:

```
.venv/
db.sqlite3
staticfiles/
__pycache__/
.pytest_cache/
.ruff_cache/
```

---

## Step 2. `compose.yml` (저장소 루트)

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: pm
      POSTGRES_USER: pm
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-pm}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pm -d pm"]
      interval: 5s
      timeout: 3s
      retries: 20
    restart: unless-stopped     # 없으면 호스트 재부팅 뒤 db만 내려가 web이 migrate에서 크래시 루프한다.
    ports:
      - "127.0.0.1:5432:5432"   # 로컬 개발·테스트용. 서버에서는 이 두 줄을 지운다.

  web:
    build: ./core
    env_file: .env
    environment:
      DATABASE_URL: postgres://pm:${POSTGRES_PASSWORD:-pm}@db:5432/pm
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  discord:
    build: ./discord_service
    env_file: .env
    environment:
      CORE_URL: http://web:8000
      DB_PATH: /data/discord.sqlite
    volumes:
      - discord_data:/data
    depends_on:
      - web
    restart: unless-stopped

  mcp:
    build: ./mcp_server
    environment:
      CORE_URL: http://web:8000
      PORT: "8080"
    depends_on:
      - web
    restart: unless-stopped

  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      - web
      - mcp
    restart: unless-stopped

volumes:
  pgdata:
  discord_data:
```

`discord` 서비스는 `CORE_TOKEN`이 준비되기 전에는 시작 직후 종료된다(환경 변수 검사). 그동안은 `docker compose up -d db web mcp cloudflared`처럼 골라서 띄운다.

---

## Step 3. `.env.example` (저장소 루트)

```
# --- core (web) ---
SECRET_KEY=change-me-to-a-long-random-string
DEBUG=0
# `web`는 compose 내부 호출용(mcp·discord가 http://web:8000 으로 부른다). 빼면 그 요청이 400이 된다.
ALLOWED_HOSTS=pm.example.com,web
CSRF_TRUSTED_ORIGINS=https://pm.example.com
SITE_URL=https://pm.example.com
POSTGRES_PASSWORD=change-me

# --- discord_service ---
CORE_TOKEN=pm_xxx            # core에서 연동 계정으로 발급한 읽기 토큰. 그 계정은 팀 관리자여야 한다
TEAM_ID=1
# 발송 대상은 웹 화면 `팀 → 알림 채널`에 등록한다. 아래는 core를 못 읽을 때 쓰는 예비값이라 비워도 된다.
DISCORD_WEBHOOK_URL=
TZ=Asia/Seoul
SEND_HOUR=9
WEEKLY_WEEKDAY=0
WEEKLY_HOUR=9
LLM_PROVIDER=
SITE_NAME=산돌이 업무

# --- cloudflared ---
CLOUDFLARE_TUNNEL_TOKEN=eyJ...
```

`.env`는 git에 넣지 않는다(`.gitignore`에 이미 있음).

---

## Step 4. 로컬 실행 확인

저장소 루트에서:

```bash
cp .env.example .env
# .env에서 ALLOWED_HOSTS=localhost,127.0.0.1  CSRF_TRUSTED_ORIGINS=http://localhost:8000  SITE_URL=http://localhost:8000  DEBUG=1 로 바꾼다.
docker compose up -d --build db web mcp
docker compose exec web python manage.py createsuperuser
docker compose logs -f web
```

확인:

- `docker compose exec web python manage.py check` 오류 없음.
- 호스트에서 `curl -s http://$(docker compose port web 8000)/healthz` 대신, `web`은 포트를 노출하지 않으므로 `docker compose exec web python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/healthz').read())"` → `{"ok": true}`.
- core 테스트를 Postgres로: `cd core && DATABASE_URL=postgres://pm:pm@localhost:5432/pm uv run pytest -q` 통과.

---

## Step 5. Proxmox 서버 준비

1. Proxmox에서 Debian 12 LXC 컨테이너 생성: CPU 2, 메모리 2 GB, 디스크 20 GB, **Options → Features에서 `nesting=1`, `keyctl=1`** 켜기(Docker 실행에 필요). 비특권 컨테이너 권장.
2. 컨테이너 안에서 Docker 설치:

```bash
apt-get update && apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
docker run --rm hello-world
```

3. 저장소를 `/opt/project-manager`에 복사(git 원격이 없으므로 `scp` 또는 `rsync`). `.venv/`, `db.sqlite3`는 복사하지 않는다.

---

## Step 6. Cloudflare Tunnel

Cloudflare 대시보드 → Zero Trust → Networks → Tunnels:

1. **Create a tunnel** → Cloudflared → 이름 `sandol-pm` → 나오는 토큰(`eyJ...`)을 `.env`의 `CLOUDFLARE_TUNNEL_TOKEN`에 넣는다.
2. **Public Hostname** 두 개 추가:

| Subdomain | Domain | Service |
|---|---|---|
| `pm` | `<도메인>` | `HTTP` `web:8000` |
| `mcp` | `<도메인>` | `HTTP` `mcp:8080` |

`web`, `mcp`는 compose 네트워크의 서비스 이름이다. cloudflared 컨테이너가 같은 네트워크에 있으므로 그대로 닿는다.

3. (선택) Security → WAF → Rate limiting rules: `(http.request.uri.path in {"/login" "/signup"})` 를 IP당 1분 20회로 제한.
4. (선택) Zero Trust → Access → Applications 로 `pm.<도메인>/admin/*` 에 이메일 인증을 걸 수 있다. 지금은 하지 않는다.

---

## Step 7. 서버에서 기동

```bash
cd /opt/project-manager
cp .env.example .env && nano .env      # 실제 값 입력. SECRET_KEY는 `python3 -c "import secrets;print(secrets.token_urlsafe(50))"`
# compose.yml의 db ports 두 줄 삭제
docker compose up -d --build db web mcp cloudflared
docker compose exec web python manage.py createsuperuser
docker compose logs --tail=50 web cloudflared
```

브라우저에서 `https://pm.<도메인>/healthz` → `{"ok": true}`. `https://pm.<도메인>/login` 열림.

초기 데이터:

1. superuser로 `/signup`이 아닌 `/login`으로 들어가 `/teams/new`에서 팀 생성(예: 산돌이 서비스). 만든 사람이 관리자가 된다.
2. `/teams/<id>/members`(팀원 관리)에서 초대 링크 발급 → 팀원에게 전달. 팀원은 `/signup` 후 링크로 참여.
3. `/teams/<id>/webhooks`(알림 채널)에서 Discord 채널 Webhook 주소를 등록하고 **[테스트 발송]**으로 확인한다. 여기 등록한 채널이 곧 알림 발송 대상이다.
4. Discord 연동 계정: `/signup`으로 `discord-bot` 계정 생성 → 초대 링크로 팀 참여 → `팀원 관리`에서 그 계정을 **관리자**로 올린다(Webhook 주소를 읽어야 한다) → 그 계정으로 `/settings/tokens`에서 **읽기** 토큰 발급 → `.env`의 `CORE_TOKEN`에 넣고 `TEAM_ID` 확인 → `docker compose up -d discord`.
5. `docker compose exec discord python -m discord_service test` → 등록한 채널 전부에 테스트 메시지.
6. 각자 `/settings/tokens`에서 개인 토큰 발급 후 GUIDE-03 Step 5 표대로 AI 클라이언트 연결. MCP URL은 `https://mcp.<도메인>`.

---

## Step 8. 상태 확인과 갱신

- UptimeRobot(무료)에 `https://pm.<도메인>/healthz` HTTP 모니터를 5분 간격으로 등록. 알림은 이메일 또는 Discord Webhook.
- `/ops`(superuser)에서 `discord` 통합의 마지막 실행과 결과를 본다.
- 코드 갱신: 파일 복사 후 `docker compose up -d --build`. 마이그레이션은 entrypoint가 자동 실행.
- 백업은 후속 과제다. 그때까지 Proxmox의 Datacenter → Backup에서 이 컨테이너를 매일 다른 스토리지로 vzdump 하도록 예약해 둔다.
- 월 1회: 각 파트에서 `uv lock --upgrade` 후 테스트 → 재빌드.

---

## Step 9. 루트 `README.md`

루트 `README.md`는 이미 목업 핸드오프 문서다. **지우지 말고 맨 앞에 "실행 안내" 절을 덧붙인다.** 기존 내용은 그 아래 "디자인 핸드오프" 제목으로 그대로 둔다. 덧붙일 내용:

1. 한 줄 소개와 세 파트(`core`, `discord_service`, `mcp_server`) 역할.
2. 문서 링크: `PLAN.md`, `docs/IMPL-PLAN.md`, `docs/SPEC.md`, `docs/GUIDE-*.md`.
3. 로컬 개발 빠른 시작: `cd core && uv sync && uv run python manage.py migrate && uv run python manage.py runserver`, 테스트 명령.
4. Docker 로컬 실행(Step 4)과 서버 배포(Step 5~7) 요약, 자세한 건 이 문서로 링크.
5. 환경 변수 표(`.env.example` 항목 설명).
6. 목업 보는 법: 루트에서 `python -m http.server 8765` 후 `산돌이 업무 목업 v2.dc.html` 열기.

---

## 완료 체크

- [x] `docker compose build` 세 이미지 모두 성공 (web 376MB · mcp 308MB · discord 269MB)
- [x] 로컬에서 `db web mcp` 기동 후 `/healthz` OK, Postgres 16으로 core 테스트 122개 통과
- [ ] Proxmox LXC 기동·`https://pm.<도메인>/healthz`  ← 사용자 인프라 필요
- [x] 팀 생성 → 초대 링크 발급 → 새 계정 가입 → 참여까지 실행 중 서버에서 확인 (참여 후 프로젝트 레일에 팀 프로젝트가 보이고 '초대 링크가 필요합니다' 안내가 사라진다)
- [x] 팀원 관리 화면에서 역할 변경·제거·초대, 알림 채널 화면에서 Webhook 등록·[테스트 발송]·끄기·삭제까지 브라우저에서 확인 (테스트 발송은 실제 Discord가 403으로 답한 것까지 화면에 표시)
- [ ] 실제 Discord 채널 테스트 메시지 수신  ← 사용자 인프라 필요 — 컨테이너 기동·설정 파싱·발송 경로는 확인. 진짜 Webhook 주소를 `팀 → 알림 채널`에 등록하면 된다
- [ ] 공개 URL로 커넥터 등록  ← 사용자 인프라 필요 — mcp 컨테이너에서 `list_tasks` 동작 확인
- [ ] UptimeRobot 모니터 등록  ← 사용자 인프라 필요
- [ ] Proxmox vzdump 예약 등록  ← 사용자 인프라 필요
- [x] `README.md` 작성 (실행 안내 절을 앞에 덧붙이고 기존 핸드오프는 그대로 뒀다)
- [x] 완료 보고서 작성 ([IMPL-REPORT.md](IMPL-REPORT.md))

커밋: `deploy: compose, cloudflared, readme`
