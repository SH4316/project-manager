import pytest
from django.utils import timezone

from accounts.models import ApiToken
from common.errors import ServiceError
from teams.models import Membership
from teams.services import (
    change_role,
    create_invite,
    is_admin,
    is_member,
    join_by_token,
    revoke_invite,
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
