# 구현 지시서 V2-04: 부하 현황과 로드맵 (4단계)

목표: 조직 하위 탭에 화면 둘을 더한다. **부하 현황**(담당자별 업무량과 스킬 태그)과 **로드맵**(마일스톤 타임라인과 프로젝트 의존성).

숫자는 전부 `reports.services.org_status()`에서 온다. 개요와 부하 현황이 다른 숫자를 보이면 안 된다.

---

## 1. Step 1. 부하 현황

### 뷰

```python
@login_required
def capacity(request, org_id):
    org = org_or_404(request.user, org_id)
    st = org_status(org)
    c = st["counts"]
    rows = st["capacity"]

    team_id = request.GET.get("team", "")
    if team_id.isdecimal():
        rows = [r for r in rows if any(t["id"] == int(team_id) for t in r["teams"])]

    picked = [t.strip() for t in request.GET.get("tags", "").split(",") if t.strip()]
    all_tags = sorted({t for r in st["capacity"] for t in r["tags"]})
    # 고른 태그를 "전부" 가진 사람이 후보다. 하나라도 가진 사람이 아니다.
    candidates = [r for r in st["capacity"] if set(picked) <= set(r["tags"])] if picked else []

    return render(request, "orgs/capacity.html", {
        "org": org, "tab": "capacity", "is_admin": can_admin(request.user, org),
        "tiles": [
            ("진행 중", c["doing"], False),
            ("검토 대기", c["review"], False),
            ("막힘", c["blocked"], True),
            ("기한 초과", c["overdue"], True),
            ("1인 평균 진행", c["avg_doing"], False),
        ],
        "rows": rows,
        "teams": org.teams.all(),
        "team_id": team_id,
        "all_tags": all_tags,
        "picked": picked,
        "candidates": candidates,
        "me_url": reverse("me"),
    })
```

타일 세 번째 값은 "0보다 크면 빨강"이다. `1인 평균 진행`은 소수 첫째 자리(`org_status`가 이미 그렇게 만든다).

### 템플릿 `orgs/capacity.html`

카드 셋이다.

1. **타일 5개** (`.tiles.five`)
2. **담당자별**: 행마다 이름(→ `?member=<id>`) · 부하 막대 · 요약 · 스킬 태그 칩 · 판정 배지

```html
<div class="load-row">
  <a class="name" href="{{ me_url }}?member={{ r.user.id }}">{{ r.user.display_name }}</a>
  <div class="grow stack" style="gap:6px">
    <div class="bar" role="img" aria-label="진행 중과 검토 대기 {{ r.load }}건">
      <i style="width:{{ r.bar }}%{% if r.over %};background:var(--danger){% endif %}"></i>
    </div>
    <span class="t12 muted">진행 중 {{ r.doing }} · 검토 대기 {{ r.review }} · 막힘 {{ r.blocked }} · 기한 초과 {{ r.overdue }}</span>
  </div>
  <div class="chips">{% for t in r.tags %}<span class="tag">{{ t }}</span>{% endfor %}</div>
  <span class="badge{% if r.over %} danger{% endif %}">{{ r.verdict }}</span>
</div>
```

카드 아래에 안내 한 줄: "막대는 진행 중 + 검토 대기 개수를 조직 최대치 기준으로 표시합니다. 이름을 누르면 그 사람의 태스크 목록으로 이동합니다."

3. **스킬 태그로 담당자 찾기**: 칩 토글(링크로 `?tags=`를 다시 만든다) + 결과 한 줄.

```
{{ picked|join:" · " }} → {{ 이름들 }} ({{ n }}명)
```
고른 태그가 없으면 "태그를 골라 담당 후보를 확인하세요.", 후보가 없으면 "조건에 맞는 사람이 없습니다."

태그가 하나도 등록되지 않은 조직에서는 이 카드에 "멤버 관리에서 스킬 태그를 넣으면 여기에서 찾을 수 있습니다."를 보여 준다.

```css
.load-row { display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: center; padding: 14px 16px; border: 1px solid var(--border); border-radius: 8px; }
.load-row .name { flex: 0 0 140px; font-size: 16px; font-weight: 600; color: var(--text-primary); text-decoration: none; }
.load-row .grow { flex: 1 1 220px; min-width: 0; }
.bar { height: 8px; border-radius: 999px; background: var(--bg-fill); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--primary); }
.tag { padding: 0 8px; border-radius: 999px; background: var(--bg-fill); font-size: 12px; line-height: 22px; }
```

`.subgroup .bar`가 이미 있으면 그 규칙을 `.bar`로 올리고 중복을 지운다.

---

## 2. Step 2. 로드맵 모델

`projects/models.py`에 더한다.

```python
class Milestone(models.Model):
    STATUSES = [("planned", "준비 중"), ("active", "진행 중"), ("done", "완료")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField("이름", max_length=100)
    start_date = models.DateField("시작일", null=True, blank=True)
    target_date = models.DateField("목표일")
    status = models.CharField("상태", max_length=7, choices=STATUSES, default="planned")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["target_date", "id"]

    def __str__(self):
        return self.name

    @property
    def status_label(self) -> str:
        return dict(self.STATUSES)[self.status]


class ProjectDependency(models.Model):
    from_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="dependencies")
    to_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="dependents")
    note = models.CharField("메모", max_length=200, blank=True)
    is_blocking = models.BooleanField("차단", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_blocking", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_project", "to_project"], name="dependency_from_to"
            ),
            models.CheckConstraint(
                condition=~models.Q(from_project=models.F("to_project")), name="dependency_not_self"
            ),
        ]
```

**마일스톤에 태스크를 연결하지 않는다.** 진행률은 그 프로젝트의 `project_stats`에서 온다. 태스크 연결은 v1 범위 밖이다.

---

## 3. Step 3. 로드맵 서비스

`projects/services.py`에 더한다. 조직 멤버면 만들 수 있다(프로젝트 생성과 같은 기준).

```python
def _add_month(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def create_milestone(*, project, name, target_date, actor, start_date=None, status="planned"):
    if not is_member(actor, project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    errors = {}
    if not (name or "").strip():
        errors["name"] = "마일스톤 이름을 입력하세요."
    if target_date is None:
        errors["target_date"] = "목표일을 선택하세요."
    if start_date and target_date and start_date > target_date:
        errors["start_date"] = "시작일은 목표일보다 앞이어야 합니다."
    if status not in dict(Milestone.STATUSES):
        errors["status"] = "알 수 없는 상태입니다."
    if errors:
        raise ServiceError(errors)
    return Milestone.objects.create(
        project=project, name=name.strip()[:100], start_date=start_date,
        target_date=target_date, status=status, created_by=actor,
    )
```

`update_milestone(ms, changes, *, actor)`는 같은 검증을 지나고 `save()`한다. 마일스톤에는 `version`이 없다(동시 편집이 문제가 될 만큼 자주 고치지 않는다).
`delete_milestone(ms, actor)`는 멤버 검사 후 삭제.

```python
def create_dependency(*, from_project, to_project, actor, note="", is_blocking=False):
    if not is_member(actor, from_project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if to_project.org_id != from_project.org_id:
        raise ServiceError({"to_project": "같은 조직의 프로젝트만 연결할 수 있습니다."})
    if to_project.pk == from_project.pk:
        raise ServiceError({"to_project": "자기 자신에게는 의존할 수 없습니다."})
    if ProjectDependency.objects.filter(from_project=from_project, to_project=to_project).exists():
        raise ServiceError({"to_project": "이미 있는 의존성입니다."})
    return ProjectDependency.objects.create(
        from_project=from_project, to_project=to_project,
        note=(note or "").strip()[:200], is_blocking=bool(is_blocking), created_by=actor,
    )
```

순환 의존성은 막지 않는다. `# ponytail: 순환은 막지 않는다. 표시만 하는 목록이라 해가 없다. 자동 일정 계산이 생기면 그때 검사한다.`

타임라인 계산:

```python
def roadmap(org, today=None) -> dict:
    """3개월 창(이번 달 1일부터). 막대는 창에 잘라 맞춘 left/width %."""
    today = today or today_kst()
    start = today.replace(day=1)
    end = _add_month(start, 3)
    span = (end - start).days
    months = [_add_month(start, i) for i in range(3)]

    qs = (
        Milestone.objects.filter(project__org=org, project__is_archived=False)
        .select_related("project")
    )
    rows, hidden = [], 0
    for ms in qs:
        s = min(ms.start_date or ms.target_date, ms.target_date)
        if ms.target_date < start or s >= end:
            hidden += 1
            continue
        a, b = max(s, start), min(ms.target_date, end)
        st = project_stats(ms.project)
        rows.append({
            "ms": ms,
            "meta": f"{ms.project.name} · {fmt_md(ms.target_date)} · 완료 {st['done']}/{st['total']}",
            "left": round((a - start).days / span * 100, 2),
            "width": round(max((b - a).days, 1) / span * 100, 2),
            "pct": round(st["done"] / st["total"] * 100) if st["total"] else 0,
            "ready": ms.status != "planned",
        })
    rows.sort(key=lambda r: (r["ms"].target_date, r["ms"].pk))
    deps = list(
        ProjectDependency.objects.filter(from_project__org=org)
        .select_related("from_project", "to_project")
    )
    return {"months": months, "rows": rows, "deps": deps, "hidden": hidden}
```

`fmt_md`는 `common.dates`에 이미 있다.

---

## 4. Step 4. 로드맵 화면

`orgs/roadmap.html` 카드 둘.

**타임라인**: 왼쪽 220px 이름 열 + 오른쪽 3등분 월 헤더.

```html
<div class="tl-head"><span class="tl-name"></span>
  <div class="tl-track">{% for m in months %}<span>{{ m.month }}월</span>{% endfor %}</div>
</div>
{% for r in rows %}
<div class="tl-row">
  <div class="tl-name">
    <span class="t16" style="font-weight:600">{{ r.ms.name }}</span>
    <span class="t12 muted">{{ r.meta }}</span>
  </div>
  <div class="tl-track">
    <div class="tl-bar{% if not r.ready %} planned{% endif %}" style="left:{{ r.left }}%;width:{{ r.width }}%">
      <i style="width:{{ r.pct }}%"></i>
    </div>
  </div>
  <div class="row">
    <button class="btn sm" hx-get="{% url 'milestone_edit' r.ms.pk %}" hx-target="#dialog" hx-swap="innerHTML">수정</button>
  </div>
</div>
{% empty %}<p class="muted">이 기간에 보여 줄 마일스톤이 없습니다.</p>{% endfor %}
{% if hidden %}<p class="muted t13">표시 기간 밖의 마일스톤 {{ hidden }}건은 보이지 않습니다.</p>{% endif %}
```

안내: "점선은 준비 중, 채워진 막대는 진행률입니다."

```css
.tl-head, .tl-row { display: flex; gap: 12px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border); }
.tl-name { flex: 0 0 220px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tl-track { flex: 1; min-width: 0; position: relative; height: 28px; display: grid; grid-template-columns: repeat(3, 1fr); font-size: 12px; color: var(--text-secondary); }
.tl-bar { position: absolute; top: 4px; height: 20px; border-radius: 6px; background: var(--primary-bg); overflow: hidden; }
.tl-bar.planned { background: var(--bg-fill); border: 1px dashed var(--text-disabled); }
.tl-bar i { display: block; height: 100%; background: var(--primary); }
@media (max-width: 700px) { .tl-name { flex-basis: 120px; } }
```

**프로젝트 의존성**: 행마다 `A → B` + 메모 + 차단 배지(차단이면 `--danger`에 700) + [삭제]. 아래에 인라인 폼(프로젝트 select 둘 · 메모 · 차단 체크 · [추가]).

[새 마일스톤]은 `<dialog>`(`orgs/_milestone_dialog.html`): 프로젝트 select · 이름 · 시작일 · 목표일 · 상태 라디오 3개.

### URL

```
orgs/<int:org_id>/capacity                       org_capacity
orgs/<int:org_id>/roadmap                        org_roadmap
orgs/<int:org_id>/milestones/new                 milestone_new
milestones/<int:milestone_id>/edit               milestone_edit
milestones/<int:milestone_id>/delete             milestone_delete   POST
orgs/<int:org_id>/dependencies                   dependency_add     POST
dependencies/<int:dependency_id>/delete          dependency_delete  POST
```

`web/views/roadmap.py`를 새로 만든다. `orgs/_tabs.html`에 두 줄을 더한다(관리자 제한 없음 — 조직 멤버 전부 본다).

```html
  <a href="{% url 'org_capacity' org.pk %}" {% if tab == "capacity" %}aria-current="page"{% endif %}>부하 현황</a>
  <a href="{% url 'org_roadmap' org.pk %}" {% if tab == "roadmap" %}aria-current="page"{% endif %}>로드맵</a>
```

---

## 5. 테스트

| 이름 | 확인 |
|---|---|
| `test_capacity_tiles_match_overview` | 타일 숫자가 `org_status().counts`와 같다 |
| `test_capacity_lists_members_without_tasks` | 태스크가 없는 멤버도 행이 있다 |
| `test_capacity_verdict_thresholds` | 부하 4 또는 초과 2 → 과부하, 부하 1 이하 → 여유 |
| `test_capacity_bar_scales_to_max` | 최대 부하인 사람이 100% |
| `test_capacity_team_filter` | `?team=`이 그 팀 멤버만 남긴다 |
| `test_skill_filter_intersection` | 두 태그를 고르면 **둘 다** 가진 사람만 후보 |
| `test_milestone_validation` | 이름 필수, 목표일 필수, 시작일 ≤ 목표일 |
| `test_roadmap_bar_clipping` | 창 앞뒤로 걸친 마일스톤이 0~100% 안으로 잘린다 |
| `test_roadmap_hides_out_of_window` | 지난달에 끝난 마일스톤은 `hidden`으로 센다 |
| `test_roadmap_progress_from_project_stats` | 진행률이 프로젝트 완료율과 같다 |
| `test_dependency_same_org_and_not_self` | 다른 조직·자기 자신은 거부 |
| `test_dependency_duplicate_rejected` | 같은 쌍을 두 번 못 넣는다 |
| `test_roadmap_tabs_visible_to_member` | 일반 멤버도 두 탭을 본다 |

## 6. 검증

```bash
cd core && uv run ruff check . && uv run pytest -q
uv run python manage.py makemigrations --check --dry-run
```

화면: 부하 현황의 타일이 개요와 같은 숫자다. 태그 칩 두 개를 고르면 후보가 줄어든다. 로드맵에서 마일스톤을 만들면 막대가 목표일 위치에 나오고, 준비 중이면 점선이다.

## 7. 완료 체크

- [ ] 부하 현황과 개요의 숫자가 같다(한 함수에서 나온다)
- [ ] 태스크 없는 멤버도 부하 행에 나온다
- [ ] 태그 찾기가 교집합이다
- [ ] 마일스톤 막대가 창 밖에서 깨지지 않는다
- [ ] 의존성 자기 참조·중복·타 조직이 막힌다
