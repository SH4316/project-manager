import urllib.error

import pytest
from django.utils import timezone

from accounts.models import ApiToken
from common.errors import ServiceError
from teams.models import DiscordWebhook, Membership
from teams.services import (
    active_webhook_urls,
    add_webhook,
    change_role,
    create_invite,
    delete_webhook,
    is_admin,
    is_member,
    join_by_token,
    remove_member,
    revoke_invite,
    send_test_message,
    set_webhook_active,
)

pytestmark = pytest.mark.django_db


def test_create_team_makes_creator_admin(team, admin):
    assert is_admin(admin, team)


def test_join_by_token_creates_membership_and_counts(team, admin, outsider):
    invite = create_invite(team, admin)
    join_by_token(outsider, invite.token)
    invite.refresh_from_db()
    assert is_member(outsider, team)
    assert invite.use_count == 1
    join_by_token(outsider, invite.token)
    invite.refresh_from_db()
    assert invite.use_count == 1


def test_join_expired_or_revoked_invite_rejected(team, admin, outsider):
    expired = create_invite(team, admin)
    expired.expires_at = timezone.now() - timezone.timedelta(days=1)
    expired.save(update_fields=["expires_at"])
    with pytest.raises(ServiceError):
        join_by_token(outsider, expired.token)

    revoked = create_invite(team, admin)
    revoke_invite(revoked, admin)
    with pytest.raises(ServiceError):
        join_by_token(outsider, revoked.token)


def test_member_cannot_create_invite(team, member):
    with pytest.raises(ServiceError):
        create_invite(team, member)


def test_cannot_demote_last_admin(team, admin):
    membership = Membership.objects.get(team=team, user=admin)
    with pytest.raises(ServiceError):
        change_role(membership, "member", admin)


def test_outsider_cannot_see_team_data_via_api(client, team, project, task, outsider):
    _, raw = ApiToken.issue(outsider, "o", "read")
    h = {"Authorization": f"Bearer {raw}"}
    assert client.get(f"/api/teams/{team.pk}", headers=h).status_code == 404
    assert client.get("/api/tasks", headers=h).json()["total"] == 0
    assert client.get("/api/projects", headers=h).json() == []


def test_outsider_cannot_open_project_page(client, project, outsider):
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/projects/{project.pk}").status_code == 404


def test_join_page_requires_login_then_joins(client, team, admin, outsider):
    invite = create_invite(team, admin)
    r = client.get(f"/join/{invite.token}")
    assert r.status_code == 302
    assert r.headers["Location"].startswith("/login?next=")
    client.login(username="outsider", password="pw12345678")
    r = client.post(f"/join/{invite.token}")
    assert r.status_code == 302
    assert r.headers["Location"] == "/today"
    assert Membership.objects.filter(team=team, user=outsider).exists()


# ---------- Discord 알림 채널 ----------

WH = "https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOp-_9876"
WH2 = "https://discord.com/api/webhooks/999999999999999999/ZzZzZzZzZzZzZzZzZzZz"


def test_member_cannot_manage_webhooks(team, admin, member):
    with pytest.raises(ServiceError):
        add_webhook(team, "알림", WH, member)
    wh = add_webhook(team, "알림", WH, admin)
    for call in (
        lambda: set_webhook_active(wh, False, member),
        lambda: delete_webhook(wh, member),
        lambda: send_test_message(wh, member, send=lambda u, t: None),
    ):
        with pytest.raises(ServiceError):
            call()
    wh.refresh_from_db()
    assert wh.is_active is True


def test_add_webhook_rejects_non_discord_urls(team, admin):
    bad = [
        "http://discord.com/api/webhooks/1/abc",  # https 아님
        "https://evil.example/api/webhooks/1/abc",  # 다른 host
        "https://discord.com.evil.example/api/webhooks/1/abc",
        "https://discord.com/api/webhooks/1",  # 토큰 없음
        "https://discord.com/api/webhooks/1/abc?wait=true",  # 덧붙은 쿼리
        "https://discord.com/api/webhooks/abc/abc",  # 채널 id가 숫자가 아님
        "",
    ]
    for url in bad:
        with pytest.raises(ServiceError):
            add_webhook(team, "알림", url, admin)
    assert DiscordWebhook.objects.count() == 0
    with pytest.raises(ServiceError):
        add_webhook(team, "  ", WH, admin)  # 이름 필수


def test_add_webhook_trims_and_blocks_duplicates(team, admin):
    wh = add_webhook(team, "  업무-알림  ", f"  {WH}  ", admin)
    assert (wh.name, wh.url) == ("업무-알림", WH)
    with pytest.raises(ServiceError):
        add_webhook(team, "또 하나", WH, admin)
    assert active_webhook_urls(team) == [WH]


def test_masked_hides_the_secret_part(team, admin):
    wh = add_webhook(team, "알림", WH, admin)
    assert "AbCdEfGhIjKlMnOp" not in wh.masked
    assert wh.masked.endswith("9876")
    short = DiscordWebhook(url="https://discord.com/api/webhooks/1/abcd")
    assert short.masked.endswith("/" + "•" * 8)  # 짧은 토큰은 뒤 네 자도 감춘다


def test_only_active_webhooks_are_send_targets(team, admin):
    a = add_webhook(team, "가", WH, admin)
    add_webhook(team, "나", WH2, admin)
    assert active_webhook_urls(team) == [WH, WH2]
    set_webhook_active(a, False, admin)
    assert active_webhook_urls(team) == [WH2]
    delete_webhook(a, admin)
    assert DiscordWebhook.objects.filter(team=team).count() == 1


def test_send_test_message_records_success_and_failure(team, admin):
    wh = add_webhook(team, "알림", WH, admin)
    sent = []
    assert send_test_message(wh, admin, send=lambda u, t: sent.append((u, t))) == (True, "")
    wh.refresh_from_db()
    assert sent[0][0] == WH and team.name in sent[0][1]
    assert wh.last_test_ok is True and wh.last_test_at is not None

    def gone(url, text):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    ok, detail = send_test_message(wh, admin, send=gone)
    wh.refresh_from_db()
    assert ok is False and "404" in detail and wh.last_test_ok is False
    assert WH not in detail  # 실패 사유에 주소가 섞이지 않는다

    ok, detail = send_test_message(
        wh, admin, send=lambda u, t: (_ for _ in ()).throw(OSError("dns"))
    )
    assert ok is False and "연결" in detail


def test_webhooks_go_away_with_the_team_not_with_the_member(team, admin, member):
    """팀원을 제거해도 팀의 알림 채널은 남는다. 등록자가 나가도 알림은 계속 나가야 한다."""
    Membership.objects.filter(team=team, user=member).update(role="admin")
    wh = add_webhook(team, "알림", WH, member)
    remove_member(Membership.objects.get(team=team, user=member), admin)
    wh.refresh_from_db()  # 채널은 팀에 딸린 것이다
    assert active_webhook_urls(team) == [WH]
