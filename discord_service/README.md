# discord_service

산돌이 태스크의 마감 알림(D-3 · D-1 · 당일 · 기한 초과)과 주간 보고를 Discord Webhook으로 보낸다.
core 코드를 import하지 않는다. core의 HTTP API로만 통신하며, 상태는 SQLite 파일 하나에 둔다.

## 환경 변수

| 이름 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `CORE_URL` | ✅ | — | core 주소. 예: `http://web:8000` |
| `CORE_TOKEN` | ✅ | — | core에서 발급한 **읽기** API 토큰 (`pm_…`) |
| `TEAM_ID` | ✅ | — | 알림을 보낼 팀 id |
| `DISCORD_WEBHOOK_URL` | ✅ | — | 채널 Webhook URL |
| `TZ` | | `Asia/Seoul` | 판정·표시 기준 시간대 |
| `SEND_HOUR` | | `9` | 마감 알림을 보낼 시각(시). 이 시각 **이후** 첫 tick에 하루 1회 |
| `WEEKLY_WEEKDAY` | | `0` | 주간 보고 요일 (0=월) |
| `WEEKLY_HOUR` | | `9` | 주간 보고 시각(시) |
| `LLM_PROVIDER` | | (빈 값) | 비우면 고정 형식 보고서. 값이 있고 실패하면 고정 형식으로 되돌아간다 |
| `DB_PATH` | | `/data/discord.sqlite` | 발송 기록 SQLite 경로 |
| `SITE_NAME` | | `산돌이 업무` | 테스트 메시지에 쓰는 이름 |

## CLI

```bash
python -m discord_service run                     # 60초 루프로 상주 (컨테이너 기본 명령)
python -m discord_service once                    # 지금 시각 기준 tick 1회
python -m discord_service test                    # 테스트 메시지 1건
python -m discord_service deadlines --date 2026-09-09   # 마감 알림 즉시 실행 (기본: 오늘)
python -m discord_service weekly --now --week-start 2026-08-31   # 주간 보고 (--now는 재발송)
python -m discord_service status                  # 최근 발송·실행 기록 JSON
```

## core 연동 계정 만들기

1. core에서 `/signup`으로 연동 전용 계정(예: `discord-bot`)을 만든다.
2. 팀 관리자가 발급한 초대 링크로 그 계정을 팀에 넣는다.
3. 그 계정으로 `/settings/tokens`에서 **읽기** 토큰을 발급해 `CORE_TOKEN`에 넣는다.
4. `TEAM_ID`는 `/teams/<id>` 주소의 숫자다.

## 로컬 실행

```bash
CORE_URL=http://localhost:8000 CORE_TOKEN=pm_xxx TEAM_ID=1 \
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... DB_PATH=./discord.sqlite \
uv run python -m discord_service test
```

Windows에서 직접 실행하려면 시스템에 IANA 시간대 DB가 없어 `TZ` 해석이 실패할 수 있다.
그때는 Docker로 실행한다(이미지에 tzdata가 들어 있다).

## 규칙

- D-3 · D-1 · 당일은 **그날에만** 보낸다. 놓친 날을 소급 발송하지 않는다.
- 중복 방지 키는 `(task_id, kind, due_date)`다. 기한이 바뀌면 새 기한 기준으로 다시 보낸다.
- 발송 직전에 태스크를 다시 읽어 완료·취소·기한 변경을 걸러낸다.
- 기한 초과는 하루 1건으로 묶어 보낸다.
- `@everyone`·역할 멘션은 보내지 않는다(`allowed_mentions.parse=["users"]`).
- 실패한 건은 자동 재시도하지 않는다.

## 테스트

```bash
uv run pytest -q
uv run ruff check .
```
