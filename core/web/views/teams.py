from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from projects.services import project_stats
from reports.services import team_status
from teams import services as tsv
from teams.models import Invite, Membership

from ..forms import InviteForm, TeamForm
from .common import apply_service_error, can_admin, current_team, team_or_404


@login_required
def team_current(request):
    team = current_team(request)
    if team is None:
        return redirect("team_list")
    return redirect("team_detail", team_id=team.pk)


@login_required
def team_list(request):
    teams = list(tsv.teams_of(request.user).order_by("name"))
    if len(teams) == 1:
        return redirect("team_detail", team_id=teams[0].pk)
    return render(request, "teams/list.html", {"teams": teams})


@login_required
def team_new(request):
    form = TeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            team = tsv.create_team(d["name"], d["purpose"], request.user)
            request.session["team_id"] = team.pk
            return redirect("team_detail", team_id=team.pk)
        except ServiceError as e:
            apply_service_error(form, e)
    return render(request, "teams/new.html", {"form": form})


@login_required
def team_detail(request, team_id):
    """팀 현황. README §3."""
    team = team_or_404(request.user, team_id)
    request.session["team_id"] = team.pk
    include_archived = request.GET.get("include_archived") == "1"
    st = team_status(team)
    c = st["counts"]
    me_url = reverse("me")
    tiles = [
        ("미완료", c["open"], f"{me_url}?member=0"),
        ("기한 초과", c["overdue"], f"{me_url}?member=0&due=overdue"),
        ("이번 주 마감", c["due_this_week"], f"{me_url}?member=0&due=this_week"),
        ("검토 대기", c["review"], f"{me_url}?member=0&status=review"),
        ("막힘", c["blocked"], f"{me_url}?member=0&status=blocked"),
        ("기한 미정", c["no_due"], f"{me_url}?member=0&due=none"),
    ]
    projects = team.projects.prefetch_related("owners").order_by("name")
    if not include_archived:
        projects = projects.filter(is_archived=False)
    return render(
        request,
        "teams/detail.html",
        {
            "team": team,
            "tiles": tiles,
            "project_rows": [(p, project_stats(p)) for p in projects],
            "by_assignee": st["by_assignee"],
            "me_url": me_url,
            "include_archived": include_archived,
            "is_admin": can_admin(request.user, team),
        },
    )


def _admin_only(request, team_id):
    """팀 관리자 전용 화면의 공통 관문. 팀원에게는 화면 자체를 숨긴다(404)."""
    team = team_or_404(request.user, team_id)
    if not can_admin(request.user, team):
        raise Http404
    return team


@login_required
def members(request, team_id):
    """팀원 관리. 역할·제거·초대에 더해, 제거 판단에 필요한 업무량을 함께 보여준다."""
    team = _admin_only(request, team_id)
    load = {r["assignee_id"]: r for r in team_status(team)["by_assignee"]}
    rows = [
        {"m": m, "load": load.get(m.user_id)}
        for m in team.memberships.select_related("user").order_by("user__display_name")
    ]
    return render(
        request,
        "teams/members.html",
        {
            "team": team,
            "rows": rows,
            "admin_count": sum(1 for r in rows if r["m"].role == "admin"),
            "invites": team.invites.filter(revoked_at__isnull=True),
            "form": InviteForm(),
            "site_url": settings.SITE_URL,
            "is_admin": True,
        },
    )


def _member_redirect(request, team_id):
    return redirect("team_members", team_id=team_id)


@login_required
@require_POST
def invite_create(request, team_id):
    team = team_or_404(request.user, team_id)
    form = InviteForm(request.POST)
    days = form.cleaned_data["days"] if form.is_valid() else 7
    try:
        invite = tsv.create_invite(team, request.user, days=days)
        messages.success(request, f"초대 링크: {settings.SITE_URL}{invite.path}")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, team.pk)


@login_required
@require_POST
def invite_revoke(request, invite_id):
    invite = get_object_or_404(Invite.objects.select_related("team"), pk=invite_id)
    team_or_404(request.user, invite.team_id)
    try:
        tsv.revoke_invite(invite, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, invite.team_id)


@login_required
@require_POST
def member_role(request, membership_id):
    membership = get_object_or_404(Membership.objects.select_related("team"), pk=membership_id)
    team_or_404(request.user, membership.team_id)
    try:
        tsv.change_role(membership, request.POST.get("role", ""), request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.team_id)


@login_required
@require_POST
def member_remove(request, membership_id):
    membership = get_object_or_404(Membership.objects.select_related("team"), pk=membership_id)
    team_or_404(request.user, membership.team_id)
    team_id = membership.team_id
    try:
        tsv.remove_member(membership, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, team_id)
