from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ConflictError, ServiceError
from projects.models import Project
from projects.services import (
    archive_project,
    create_project,
    project_stats,
    restore_project,
    update_project,
)
from tasks import services as ts
from tasks.models import Task

from ..forms import LinkForm, ProjectForm, TaskInlineForm
from .common import (
    CONFLICT_MSG,
    apply_service_error,
    can_admin,
    hx_redirect,
    new_idem,
    project_or_404,
    rows_for,
    team_or_404,
)


def _owner_ids(form) -> set[int]:
    """체크된 관리자 pk 집합. bound form의 value()는 raw 문자열이라 int()가 터질 수 있다."""
    ids = set()
    for x in form["owners"].value() or []:
        pk = getattr(x, "pk", x)
        try:
            ids.add(int(pk))
        except (TypeError, ValueError):
            continue
    return ids


def _dialog(request, form, team, project=None):
    """프로젝트 생성·수정 모달 부분 템플릿."""
    return render(
        request,
        "projects/_dialog.html",
        {
            "form": form,
            "team": team,
            "project": project,
            "members": team.members.filter(is_active=True).order_by("display_name"),
            "checked_owner_ids": _owner_ids(form),
            "status_options": [
                (code, label, Project.STATUS_DESC[code]) for code, label in Project.STATUSES
            ],
            "status_value": form["status"].value() or "preparing",
        },
    )


@login_required
def project_new(request):
    team = team_or_404(request.user, request.GET.get("team") or request.POST.get("team"))
    form = ProjectForm(request.POST or None, team=team)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            p = create_project(
                team=team,
                name=d["name"],
                purpose=d["purpose"],
                owners=list(d["owners"]),
                status=d["status"],
                actor=request.user,
                source="web",
            )
            request.session["team_id"] = team.pk
            return hx_redirect(request, reverse("project_detail", args=[p.pk]))
        except ServiceError as e:
            apply_service_error(form, e)
    return _dialog(request, form, team)


@login_required
def project_edit(request, project_id):
    project = project_or_404(request.user, project_id)
    initial = {
        "name": project.name,
        "purpose": project.purpose,
        "status": project.status,
        "owners": list(project.owners.all()),
        "version": project.version,
    }
    form = ProjectForm(request.POST or None, team=project.team, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        changes = {
            "name": d["name"],
            "purpose": d["purpose"],
            "owners": list(d["owners"]),
            "status": d["status"],
        }
        try:
            update_project(
                project,
                changes,
                actor=request.user,
                source="web",
                expected_version=d["version"] or 0,
            )
            return hx_redirect(request, reverse("project_detail", args=[project.pk]))
        except ServiceError as e:
            apply_service_error(form, e)
        except ConflictError:
            form.add_error(None, CONFLICT_MSG)
    return _dialog(request, form, project.team, project)


@login_required
def project_detail(request, project_id):
    project = project_or_404(request.user, project_id)
    request.session["team_id"] = project.team_id
    view = "board" if request.GET.get("view") == "board" else "list"
    include_closed = request.GET.get("include_closed") == "1"
    qs = project.tasks.select_related("project", "assignee")
    if not include_closed:
        qs = qs.filter(status__in=Task.OPEN)
    rows = rows_for(request.user, sorted(qs, key=ts.by_due))
    columns = [
        (code, label, [r for r in rows if r["task"].status == code])
        for code, label in Task.STATUSES
        if code in Task.OPEN or include_closed
    ]
    form = TaskInlineForm(
        team=project.team,
        initial={"assignee": request.user.pk, "priority": 5, "idem": new_idem()},
    )
    return render(
        request,
        "projects/detail.html",
        {
            "project": project,
            "owners": list(project.owners.all()),
            "links": project.links.all(),
            "stats": project_stats(project),
            "view": view,
            "include_closed": include_closed,
            "rows": rows,
            "columns": columns,
            "form": form,
            "form_open": request.GET.get("new") == "1",
            "is_admin": can_admin(request.user, project.team),
            "link_form": LinkForm(),
        },
    )


@login_required
@require_POST
def task_create(request, project_id):
    """인라인 태스크 폼. 성공하면 프로젝트 화면으로 돌아가며 #task-{id}로 패널을 연다."""
    project = project_or_404(request.user, project_id)
    form = TaskInlineForm(request.POST, team=project.team)
    if form.is_valid():
        d = form.cleaned_data
        try:
            task = ts.create_task(
                project=project,
                title=d["title"],
                actor=request.user,
                source="web",
                assignee=d["assignee"],
                priority=d["priority"],
                due_date=d["due_date"],
                no_due_reason=d["no_due_reason"],
                idempotency_key=d["idem"] or None,
            )
            return hx_redirect(
                request, reverse("project_detail", args=[project.pk]) + f"#task-{task.pk}"
            )
        except ServiceError as e:
            apply_service_error(form, e)
    return render(
        request,
        "projects/_task_form.html",
        {"form": form, "project": project, "form_open": True},
    )


@login_required
@require_POST
def project_archive(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        archive_project(project, actor=request.user, source="web")
        messages.success(request, "프로젝트를 보관했습니다.")
    except ServiceError as e:
        msg = e.errors.get("tasks")
        messages.error(
            request,
            f"미완료 태스크가 있어 보관할 수 없습니다: {msg}"
            if msg
            else " ".join(e.errors.values()),
        )
    return redirect("project_detail", project_id=project.pk)


@login_required
@require_POST
def project_restore(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        restore_project(project, actor=request.user, source="web")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("project_detail", project_id=project.pk)


@login_required
@require_POST
def link_add(request, project_id):
    project = project_or_404(request.user, project_id)
    form = LinkForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            ts.add_link(
                actor=request.user,
                project=project,
                title=d["title"],
                url=d["url"],
                kind=d["kind"],
            )
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
    else:
        messages.error(request, "링크 입력이 올바르지 않습니다.")
    return redirect("project_detail", project_id=project.pk)
