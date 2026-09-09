from .views.common import current_team

NAV_BY_URL = {
    "today": "today",
    "today_quick": "today",
    "me": "me",
    "team": "team",
    "team_list": "team",
    "team_detail": "team",
    "team_members": "team",
    "team_new": "team",
    "search": "search",
}


def shell(request):
    """base.html 셸: 현재 팀, 프로젝트 레일, nav 강조, 닫기 후 돌아갈 주소."""
    if not request.user.is_authenticated:
        return {}
    team = current_team(request)
    match = request.resolver_match
    url_name = match.url_name if match else ""
    return {
        "current_team": team,
        "nav_projects": team.projects.filter(is_archived=False).order_by("name") if team else [],
        "nav": NAV_BY_URL.get(url_name, ""),
        "current_project_id": match.kwargs.get("project_id") if match else None,
        "page_url": request.get_full_path(),
        "team_count": request.user.teams.count(),
    }
