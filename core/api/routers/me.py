from ninja import Router

from teams.models import Membership

from ..schemas import MeOut

router = Router(tags=["me"])


@router.get("/me", response=MeOut)
def me(request):
    u = request.auth
    memberships = Membership.objects.filter(user=u).select_related("team").order_by("team__name")
    return {
        "id": u.pk,
        "username": u.username,
        "display_name": u.display_name,
        "discord_user_id": u.discord_user_id,
        "auto_pull_days": u.auto_pull_days,
        "teams": [
            {"id": m.team_id, "name": m.team.name, "purpose": m.team.purpose, "role": m.role}
            for m in memberships
        ],
    }
