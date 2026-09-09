from datetime import date, timedelta

from django.db.models import Count, Q

from common.dates import kst_week_range, today_kst, week_bounds
from tasks.brief import task_brief, user_brief
from tasks.models import ChangeLog, Task


def _open_qs(team):
    return Task.objects.filter(project__team=team, project__is_archived=False, status__in=Task.OPEN)


def team_status(team) -> dict:
    """팀 현황 지표. 키: counts, by_project, by_assignee, projects_without_owner"""
    today = today_kst()
    monday, sunday = week_bounds(today)
    open_qs = _open_qs(team)
    counts = {
        "open": open_qs.count(),
        "overdue": open_qs.filter(due_date__lt=today).count(),
        "due_this_week": open_qs.filter(due_date__gte=monday, due_date__lte=sunday).count(),
        "review": open_qs.filter(status="review").count(),
        "blocked": open_qs.filter(status="blocked").count(),
        "no_due": open_qs.filter(due_date__isnull=True).count(),
    }
    projects = (
        team.projects.filter(is_archived=False)
        .prefetch_related("owners")
        .annotate(
            open_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN)),
            overdue_count=Count(
                "tasks", filter=Q(tasks__status__in=Task.OPEN, tasks__due_date__lt=today)
            ),
            review_count=Count("tasks", filter=Q(tasks__status="review")),
            blocked_count=Count("tasks", filter=Q(tasks__status="blocked")),
            done_count=Count("tasks", filter=Q(tasks__status="done")),
            total_count=Count("tasks", filter=~Q(tasks__status="cancelled")),
        )
    )
    by_project = [
        {
            "id": p.pk,
            "name": p.name,
            "status": p.status,
            "owners": [user_brief(u) for u in p.owners.all()],
            "open": p.open_count,
            "overdue": p.overdue_count,
            "review": p.review_count,
            "blocked": p.blocked_count,
            "done": p.done_count,
            "total": p.total_count,
        }
        for p in projects
    ]
    by_assignee = list(
        open_qs.values("assignee_id", "assignee__display_name")
        .annotate(
            open=Count("id"),
            overdue=Count("id", filter=Q(due_date__lt=today)),
            review=Count("id", filter=Q(status="review")),
            blocked=Count("id", filter=Q(status="blocked")),
        )
        .order_by("-open")
    )
    projects_without_owner = list(
        team.projects.filter(is_archived=False, owners__isnull=True).values("id", "name")
    )
    return {
        "counts": counts,
        "by_project": by_project,
        "by_assignee": by_assignee,
        "projects_without_owner": projects_without_owner,
    }


def weekly(team, week_start: date) -> dict:
    """주간 집계. week_start는 월요일이어야 한다."""
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    start, end = kst_week_range(week_start)
    period_end = week_start + timedelta(days=7)
    this_monday, this_sunday = week_bounds(period_end)
    today = today_kst()

    team_task_ids = Task.objects.filter(project__team=team).values("id")
    logs = ChangeLog.objects.filter(
        target_type="task",
        field="status",
        target_id__in=team_task_ids,
        created_at__gte=start,
        created_at__lt=end,
    )
    completed_ids = set(logs.filter(new_value="done").values_list("target_id", flat=True))
    reopened_ids = set(
        logs.filter(
            old_value__in=["done", "cancelled"], new_value__in=["todo", "doing"]
        ).values_list("target_id", flat=True)
    )

    def briefs(ids):
        qs = (
            Task.objects.filter(pk__in=ids)
            .select_related("project", "assignee")
            .order_by("project__name", "id")
        )
        return [task_brief(t) for t in qs]

    open_qs = _open_qs(team).select_related("project", "assignee")
    due_this_week = [
        task_brief(t)
        for t in open_qs.filter(due_date__gte=this_monday, due_date__lte=this_sunday).order_by(
            "due_date", "id"
        )
    ]
    overdue = [task_brief(t) for t in open_qs.filter(due_date__lt=today).order_by("due_date", "id")]
    blocked = [task_brief(t) for t in open_qs.filter(status="blocked").order_by("id")]

    by_project = []
    for p in team.projects.filter(is_archived=False).order_by("name"):
        p_ids = set(Task.objects.filter(project=p).values_list("id", flat=True))
        by_project.append(
            {
                "project": {"id": p.pk, "name": p.name, "status": p.status},
                "completed": len(completed_ids & p_ids),
                "reopened": len(reopened_ids & p_ids),
                "open": open_qs.filter(project=p).count(),
                "overdue": open_qs.filter(project=p, due_date__lt=today).count(),
                "blocked": open_qs.filter(project=p, status="blocked").count(),
            }
        )

    return {
        "team": {"id": team.pk, "name": team.name},
        "period_start": week_start.isoformat(),
        "period_end": period_end.isoformat(),
        "completed": briefs(completed_ids),
        "reopened": briefs(reopened_ids),
        "due_this_week": due_this_week,
        "overdue": overdue,
        "blocked": blocked,
        "by_project": by_project,
        "counts": {
            "completed": len(completed_ids),
            "reopened": len(reopened_ids),
            "due_this_week": len(due_this_week),
            "overdue": len(overdue),
            "blocked": len(blocked),
            "open": open_qs.count(),
            "review": open_qs.filter(status="review").count(),
            "no_due": open_qs.filter(due_date__isnull=True).count(),
        },
        "members": [
            user_brief(u) for u in team.members.filter(is_active=True).order_by("display_name")
        ],
    }
