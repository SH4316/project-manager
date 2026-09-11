import pytest

from common.dates import today_kst
from orgs.services import add_team_member, create_team
from reports.services import org_status
from tasks.services import create_task, transition

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged(client, member):
    client.login(username="member1", password="pw12345678")
    return client


def test_capacity_tiles_match_overview(logged, org, project, task):
    st = org_status(org)
    c = st["counts"]
    body = logged.get(f"/orgs/{org.pk}/capacity").content.decode()
    assert f">{c['doing']}<" in body
    assert f">{c['review']}<" in body
    assert f">{c['blocked']}<" in body
    assert f">{c['overdue']}<" in body


def test_capacity_lists_members_without_tasks(logged, org, admin, member):
    """admin은 태스크가 없어도 부하 행에 나와야 한다."""
    body = logged.get(f"/orgs/{org.pk}/capacity").content.decode()
    assert admin.display_name in body
    assert member.display_name in body


def test_capacity_verdict_thresholds(logged, org, project, member):
    due = today_kst()
    for i in range(4):
        t = create_task(project=project, title=f"t{i}", actor=member, source="web", due_date=due)
        transition(t, "doing", actor=member, source="web", expected_version=t.version)
    for r in org_status(org)["capacity"]:
        if r["user"]["id"] == member.pk:
            assert r["over"] is True
            assert r["verdict"] == "과부하"


def test_capacity_bar_scales_to_max(logged, org, project, member, admin):
    t = create_task(project=project, title="많음", actor=member, source="web", due_date=today_kst())
    transition(t, "doing", actor=member, source="web", expected_version=t.version)
    rows = {r["user"]["id"]: r for r in org_status(org)["capacity"]}
    assert rows[member.pk]["bar"] == 100
    assert rows[admin.pk]["bar"] == 0


def test_capacity_team_filter(logged, org, project, member, admin):
    team = create_team(org=org, name="백엔드", actor=admin)
    add_team_member(team, member, admin)
    body = logged.get(f"/orgs/{org.pk}/capacity?team={team.pk}").content.decode()
    assert member.display_name in body
    assert admin.display_name not in body


def test_skill_filter_intersection(logged, org, admin, member):
    """두 태그를 고르면 '전부' 가진 사람만 후보다. admin은 파이썬만 가져 후보에서 빠진다."""
    from orgs.models import OrgMembership
    from orgs.services import set_tags

    set_tags(OrgMembership.objects.get(org=org, user=member), ["파이썬", "장고"], admin)
    set_tags(OrgMembership.objects.get(org=org, user=admin), ["파이썬"], admin)
    r = logged.get(f"/orgs/{org.pk}/capacity?tags=파이썬,장고")
    candidate_ids = {c["user"]["id"] for c in r.context["candidates"]}
    assert candidate_ids == {member.pk}


def test_roadmap_tabs_visible_to_member(logged, org):
    body = logged.get(f"/orgs/{org.pk}").content.decode()
    assert "부하 현황" in body
    assert "로드맵" in body
    assert logged.get(f"/orgs/{org.pk}/roadmap").status_code == 200
