from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import Invite, Membership, Team


def teams_of(user):
    """user가 속한 팀 queryset."""
    return Team.objects.filter(memberships__user=user).distinct()


def is_member(user, team) -> bool:
    return Membership.objects.filter(team=team, user=user).exists()


def is_admin(user, team) -> bool:
    return Membership.objects.filter(team=team, user=user, role="admin").exists()


def require_admin(user, team):
    if not is_admin(user, team):
        raise ServiceError({"team": "팀 관리자만 할 수 있습니다."})


@transaction.atomic
def create_team(name: str, purpose: str, actor) -> Team:
    name = name.strip()
    if not name:
        raise ServiceError({"name": "팀 이름을 입력하세요."})
    team = Team.objects.create(name=name, purpose=purpose.strip(), created_by=actor)
    Membership.objects.create(team=team, user=actor, role="admin")
    return team


def create_invite(team, actor, days: int = 7) -> Invite:
    require_admin(actor, team)
    if not 1 <= days <= 90:
        raise ServiceError({"days": "만료일은 1~90일 사이여야 합니다."})
    expires_at = timezone.now() + timezone.timedelta(days=days)
    return Invite.objects.create(team=team, created_by=actor, expires_at=expires_at)


def revoke_invite(invite, actor):
    require_admin(actor, invite.team)
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])


@transaction.atomic
def join_by_token(user, token: str) -> Team:
    invite = Invite.objects.select_for_update().select_related("team").filter(token=token).first()
    if invite is None or not invite.is_usable:
        raise ServiceError({"token": "초대 링크가 유효하지 않거나 만료되었습니다."})
    _, created = Membership.objects.get_or_create(
        team=invite.team, user=user, defaults={"role": "member"}
    )
    if created:
        invite.use_count += 1
        invite.save(update_fields=["use_count"])
    return invite.team


def change_role(membership, role: str, actor):
    require_admin(actor, membership.team)
    if role not in dict(Membership.ROLES):
        raise ServiceError({"role": "알 수 없는 역할입니다."})
    if membership.role == "admin" and role != "admin" and _admin_count(membership.team) <= 1:
        raise ServiceError({"role": "마지막 관리자의 역할은 바꿀 수 없습니다."})
    membership.role = role
    membership.save(update_fields=["role"])


def remove_member(membership, actor):
    require_admin(actor, membership.team)
    if membership.role == "admin" and _admin_count(membership.team) <= 1:
        raise ServiceError({"member": "마지막 관리자는 제거할 수 없습니다."})
    membership.delete()


def _admin_count(team) -> int:
    return Membership.objects.filter(team=team, role="admin").count()
