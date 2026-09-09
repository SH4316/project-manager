from datetime import timedelta

import pytest

from accounts.models import ApiToken, User
from common.dates import today_kst
from projects.services import create_project
from tasks.services import create_task
from teams.models import Membership
from teams.services import create_team


@pytest.fixture
def admin(db):
    return User.objects.create_user("admin1", password="pw12345678", display_name="관리자")


@pytest.fixture
def member(db):
    return User.objects.create_user(
        "member1", password="pw12345678", display_name="팀원", discord_user_id="111"
    )


@pytest.fixture
def outsider(db):
    return User.objects.create_user("outsider", password="pw12345678", display_name="외부인")


@pytest.fixture
def team(admin, member):
    t = create_team("산돌이", "학생 챗봇 서비스", admin)
    Membership.objects.create(team=t, user=member, role="member")
    return t


@pytest.fixture
def project(team, admin):
    return create_project(team=team, name="학식 API", actor=admin, owners=[admin], status="active")


@pytest.fixture
def task(project, member):
    return create_task(
        project=project,
        title="메뉴 누락 개선",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=3),
    )


@pytest.fixture
def write_token(member):
    _, raw = ApiToken.issue(member, "t", "write")
    return raw


@pytest.fixture
def read_token(member):
    _, raw = ApiToken.issue(member, "r", "read")
    return raw


@pytest.fixture
def api(client, write_token):
    """Bearer 인증이 붙은 간단한 API 클라이언트."""

    class Api:
        def _h(self, extra=None):
            h = {"Authorization": f"Bearer {write_token}"}
            h.update(extra or {})
            return h

        def get(self, url, **kw):
            return client.get(url, headers=self._h(kw.pop("headers", None)), **kw)

        def post(self, url, data=None, **kw):
            return client.post(
                url,
                data=data,
                content_type="application/json",
                headers=self._h(kw.pop("headers", None)),
                **kw,
            )

        def patch(self, url, data=None, **kw):
            return client.patch(
                url,
                data=data,
                content_type="application/json",
                headers=self._h(kw.pop("headers", None)),
                **kw,
            )

        def delete(self, url, **kw):
            return client.delete(url, headers=self._h(kw.pop("headers", None)), **kw)

    return Api()
