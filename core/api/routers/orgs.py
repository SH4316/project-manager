from ninja import Router
from ninja.errors import HttpError

from orgs.models import Invite, OrgMembership
from orgs.services import create_invite, revoke_invite
from reports.services import org_status
from tasks.brief import user_brief

from ..context import ctx, org_or_404
from ..schemas import ErrorOut, InviteIn, InviteOut, OrgOut, TeamOut, UserBrief
from ..serialize import invite_out, project_out

router = Router(tags=["orgs"])


@router.get("/{org_id}", response=OrgOut)
def get_org(request, org_id: int):
    org = org_or_404(request, org_id)
    role = OrgMembership.objects.get(org=org, user=request.auth).role
    projects = org.projects.filter(is_archived=False).prefetch_related("owners", "teams")
    teams = org.teams.all()
    return {
        "id": org.pk,
        "name": org.name,
        "purpose": org.purpose,
        "role": role,
        "projects": [project_out(p) for p in projects],
        "teams": [
            {
                "id": t.pk,
                "name": t.name,
                "purpose": t.purpose,
                "member_count": t.members.count(),
            }
            for t in teams
        ],
    }


@router.get("/{org_id}/members", response=list[UserBrief])
def members(request, org_id: int):
    org = org_or_404(request, org_id)
    return [user_brief(u) for u in org.members.filter(is_active=True).order_by("display_name")]


@router.get("/{org_id}/teams", response=list[TeamOut])
def teams(request, org_id: int):
    org = org_or_404(request, org_id)
    return [
        {
            "id": t.pk,
            "name": t.name,
            "purpose": t.purpose,
            "member_count": t.members.count(),
        }
        for t in org.teams.all()
    ]


@router.get("/{org_id}/status", response=dict)
def status(request, org_id: int):
    return org_status(org_or_404(request, org_id))


@router.post("/{org_id}/invites", response={201: InviteOut, 400: ErrorOut})
def create_invite_ep(request, org_id: int, payload: InviteIn):
    org = org_or_404(request, org_id)
    inv = create_invite(org, ctx(request)["actor"], days=payload.days)
    return 201, invite_out(inv)


@router.delete("/invites/{invite_id}", response={204: None})
def delete_invite(request, invite_id: int):
    inv = Invite.objects.filter(pk=invite_id).select_related("org").first()
    if inv is None:
        raise HttpError(404, "초대를 찾을 수 없습니다.")
    org_or_404(request, inv.org_id)
    revoke_invite(inv, ctx(request)["actor"])
    return 204, None
