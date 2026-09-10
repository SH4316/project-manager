import json
import urllib.error
import urllib.request

from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import WEBHOOK_RE, DiscordWebhook, Invite, Membership, Team


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
    team = Team.objects.create(name=name[:100], purpose=purpose.strip()[:200], created_by=actor)
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


# ---------- Discord 알림 채널 ----------

WEBHOOK_HELP = "Discord 채널 → 설정 → 연동 → 웹후크에서 만든 주소를 붙여넣으세요."


def webhooks_of(team):
    return DiscordWebhook.objects.filter(team=team).select_related("created_by")


def active_webhook_urls(team) -> list[str]:
    """discord 서비스가 읽어 가는 발송 대상. 순서는 이름순으로 고정한다."""
    return list(webhooks_of(team).filter(is_active=True).values_list("url", flat=True))


def add_webhook(team, name: str, url: str, actor) -> DiscordWebhook:
    require_admin(actor, team)
    name, url = name.strip()[:50], url.strip()
    if not name:
        raise ServiceError({"name": "채널 이름을 입력하세요."})
    if not WEBHOOK_RE.match(url):
        raise ServiceError({"url": "Discord Webhook 주소 형식이 아닙니다."})
    if DiscordWebhook.objects.filter(team=team, url=url).exists():
        raise ServiceError({"url": "이미 등록한 Webhook입니다."})
    return DiscordWebhook.objects.create(team=team, name=name, url=url, created_by=actor)


def set_webhook_active(webhook, active: bool, actor):
    require_admin(actor, webhook.team)
    if webhook.is_active != active:
        webhook.is_active = active
        webhook.save(update_fields=["is_active"])


def delete_webhook(webhook, actor):
    require_admin(actor, webhook.team)
    webhook.delete()


def send_test_message(webhook, actor, send=None) -> tuple[bool, str]:
    """확인용 메시지 1건을 보내고 결과를 기록한다. (성공?, 사유) 를 돌려준다.

    실패 사유에 URL이 섞이지 않도록 예외 원문은 쓰지 않는다(GUIDE-00 §3).
    """
    require_admin(actor, webhook.team)
    send = send or post_discord
    try:
        send(webhook.url, f"✅ {webhook.team.name} 알림 연결 확인")
        ok, detail = True, ""
    except urllib.error.HTTPError as e:
        ok, detail = (
            False,
            f"Discord 응답 {e.code}" + (" (삭제된 Webhook)" if e.code == 404 else ""),
        )
    except Exception:  # noqa: BLE001  네트워크·DNS·타임아웃
        ok, detail = False, "Discord에 연결하지 못했습니다."
    DiscordWebhook.objects.filter(pk=webhook.pk).update(
        last_test_at=timezone.now(), last_test_ok=ok, last_test_detail=detail
    )
    return ok, detail


def post_discord(url: str, text: str) -> None:
    """core가 Discord로 직접 보내는 유일한 곳(등록 확인용 1건).

    정기 알림은 discord 서비스의 일이다. 주소는 add_webhook의 WEBHOOK_RE로 이미 검증되어
    discord.com 밖으로는 나가지 않는다.
    """
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()
