from ninja import Router

from orgs.models import OrgMembership

from ..schemas import MeOut

router = Router(tags=["me"])


@router.get("/me", response=MeOut)
def me(request):
    u = request.auth
    memberships = OrgMembership.objects.filter(user=u).select_related("org").order_by("org__name")
    return {
        "id": u.pk,
        "username": u.username,
        "display_name": u.display_name,
        "discord_user_id": u.discord_user_id,
        "auto_pull_days": u.auto_pull_days,
        "orgs": [
            {"id": m.org_id, "name": m.org.name, "purpose": m.org.purpose, "role": m.role}
            for m in memberships
        ],
    }
