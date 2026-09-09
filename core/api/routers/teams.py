from ninja import Router
from ninja.errors import HttpError

from reports.services import team_status
from tasks.brief import user_brief
from teams.models import Invite, Membership
from teams.services import create_invite, revoke_invite

from ..context import ctx, team_or_404
from ..schemas import ErrorOut, InviteIn, InviteOut, TeamOut, UserBrief
from ..serialize import invite_out, project_out

router = Router(tags=["teams"])


@router.get("/{team_id}", response=TeamOut)
def get_team(request, team_id: int):
    team = team_or_404(request, team_id)
    role = Membership.objects.get(team=team, user=request.auth).role
    projects = team.projects.filter(is_archived=False).prefetch_related("owners")
    return {
        "id": team.pk,
        "name": team.name,
        "purpose": team.purpose,
        "role": role,
        "projects": [project_out(p) for p in projects],
    }


@router.get("/{team_id}/members", response=list[UserBrief])
def members(request, team_id: int):
    team = team_or_404(request, team_id)
    return [user_brief(u) for u in team.members.filter(is_active=True).order_by("display_name")]


@router.get("/{team_id}/status", response=dict)
def status(request, team_id: int):
    return team_status(team_or_404(request, team_id))


@router.post("/{team_id}/invites", response={201: InviteOut, 400: ErrorOut})
def create_invite_ep(request, team_id: int, payload: InviteIn):
    team = team_or_404(request, team_id)
    inv = create_invite(team, ctx(request)["actor"], days=payload.days)
    return 201, invite_out(inv)


@router.delete("/invites/{invite_id}", response={204: None})
def delete_invite(request, invite_id: int):
    inv = Invite.objects.filter(pk=invite_id).select_related("team").first()
    if inv is None:
        raise HttpError(404, "초대를 찾을 수 없습니다.")
    team_or_404(request, inv.team_id)
    revoke_invite(inv, ctx(request)["actor"])
    return 204, None
