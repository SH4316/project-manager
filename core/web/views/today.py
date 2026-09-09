from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User
from common.dates import fmt_md
from common.errors import ServiceError
from tasks import services as ts
from tasks.models import Task

from ..forms import QuickTaskForm
from .common import (
    apply_service_error,
    due_label,
    hx_redirect,
    new_idem,
    render_row,
    rows_for,
    task_or_404,
    trigger,
    week_days,
)

ROW_OPTS = "next,move,noassignee,today"
WEEKDAYS = "월화수목금토일"
HOURS = [f"{h:02d}:00" for h in range(9, 19)]


def _ctx(request):
    v = ts.today_view(request.user)
    day = v["date"]
    v["date_label"] = f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"
    v["today_hint"] = f"오늘 태스크 {v['counts']['today']}건" if v["focus"] else "오늘 태스크 없음"
    v["rows"] = rows_for(request.user, v["items"], ROW_OPTS)
    v["done_rows"] = rows_for(request.user, v["done_today"], "noassignee,notoday,today")
    v["auto_pull_choices"] = User.AUTO_PULL_CHOICES
    v["schedule_open"] = request.GET.get("schedule") == "1"
    v["focus_due"] = due_label(v["focus"]) if v["focus"] else ""
    return v


def _schedule(request, day: date) -> dict:
    """일정 카드. cal=time|month, day=YYYY-MM-DD. 기한에 시각이 없으므로 시간표는 눈금과 '종일' 목록만."""
    mode = "month" if request.GET.get("cal") == "month" else "time"
    try:
        sel = date.fromisoformat(request.GET.get("day", "")) if request.GET.get("day") else day
    except ValueError:
        sel = day
    my_open = Task.objects.filter(assignee=request.user, status__in=Task.OPEN).select_related(
        "project"
    )
    counts = dict(
        my_open.filter(due_date__year=sel.year, due_date__month=sel.month)
        .values_list("due_date")
        .annotate(n=Count("id"))
    )
    cells = [
        None
        if d is None
        else {
            "day": d.day,
            "n": counts.get(d, 0),
            "today": d == day,
            "sel": d == sel,
            "url": f"{reverse('today')}?schedule=1&cal=month&day={d.isoformat()}",
            "aria": f"{d.month}월 {d.day}일 마감 {counts.get(d, 0)}건",
        }
        for d in week_days(sel)
    ]
    sel_tasks = sorted(my_open.filter(due_date=sel), key=ts.by_due)
    return {
        "cal_mode": mode,
        "cal_title": f"{sel.year}년 {sel.month}월"
        if mode == "month"
        else f"{fmt_md(day)} ({WEEKDAYS[day.weekday()]})",
        "cal_cells": cells,
        "cal_sel_label": f"{fmt_md(sel)} 마감 {len(sel_tasks)}건",
        "cal_sel_tasks": sel_tasks,
        "due_today_tasks": sorted(my_open.filter(due_date=day), key=ts.by_due),
        "hours": HOURS,
    }


@login_required
def today(request):
    v = _ctx(request)
    part = request.GET.get("part")
    if part == "head":
        return render(request, "today/_head.html", v)
    if part == "list":
        return render(request, "today/_list.html", v)
    v["quick_open"] = request.GET.get("quick") == "1"
    v["form"] = QuickTaskForm(user=request.user, initial={"idem": new_idem(), "priority": 5})
    if v["schedule_open"]:
        v.update(_schedule(request, v["date"]))
    return render(request, "today.html", v)


def head(request, error=None):
    """오늘 화면 머리(날짜·지표·지금 할 일 카드). tasks.task_status가 from=head일 때도 부른다."""
    v = _ctx(request)
    v["error"] = error
    return render(request, "today/_head.html", v)


def _list(request):
    return render(request, "today/_list.html", _ctx(request))


def _after_change(request, task):
    """오늘 화면 안이면 목록 전체, 다른 화면이면 그 행만 돌려준다. 머리는 today-changed로 갱신된다."""
    if "today" in request.GET.get("opts", ""):
        return trigger(_list(request), "today-changed")
    return trigger(render_row(request, task), "today-changed")


@login_required
@require_POST
def quick_add(request):
    form = QuickTaskForm(request.POST, user=request.user)
    if form.is_valid():
        d = form.cleaned_data
        try:
            task = ts.create_task(
                project=d["project"],
                title=d["title"],
                actor=request.user,
                source="web",
                priority=d["priority"],
                due_date=d["due_date"],
                no_due_reason=d["no_due_reason"],
                idempotency_key=d["idem"] or None,
            )
            ts.today_add(request.user, task)
            return hx_redirect(request, reverse("today"))
        except ServiceError as e:
            apply_service_error(form, e)
    return render(request, "today/_quick.html", {"form": form, "quick_open": True})


@login_required
@require_POST
def add(request, task_id):
    task = task_or_404(request.user, task_id)
    ts.today_add(request.user, task)
    return _after_change(request, task)


@login_required
@require_POST
def exclude(request, task_id):
    task = task_or_404(request.user, task_id)
    ts.today_exclude(request.user, task)
    return _after_change(request, task)


@login_required
@require_POST
def restore(request):
    ts.today_restore_excluded(request.user)
    return trigger(_list(request), "today-changed")


@login_required
@require_POST
def move(request, task_id, direction):
    ts.today_move(request.user, task_or_404(request.user, task_id), direction)
    return _list(request)


@login_required
@require_POST
def auto_pull(request):
    try:
        ts.today_set_auto_pull(request.user, int(request.POST.get("auto_pull_days", "5")))
    except (ValueError, ServiceError):
        pass
    return trigger(_list(request), "today-changed")
