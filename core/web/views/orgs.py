from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from github import writes as gh_writes
from orgs import services as osv
from orgs.governance import governance_text
from orgs.models import Invite, OrgMembership
from projects.services import project_stats
from reports.services import org_status

from ..forms import InviteForm, OrgForm
from .common import apply_service_error, can_admin, current_org, org_or_404


@login_required
def org_current(request):
    org = current_org(request)
    if org is None:
        return redirect("org_list")
    return redirect("org_detail", org_id=org.pk)


@login_required
def org_list(request):
    orgs = list(osv.orgs_of(request.user).order_by("name"))
    if len(orgs) == 1:
        return redirect("org_detail", org_id=orgs[0].pk)
    return render(request, "orgs/list.html", {"orgs": orgs})


@login_required
def org_new(request):
    form = OrgForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            org = osv.create_org(d["name"], d["purpose"], request.user)
            request.session["org_id"] = org.pk
            return redirect("org_detail", org_id=org.pk)
        except ServiceError as e:
            apply_service_error(form, e)
    return render(request, "orgs/new.html", {"form": form})


@login_required
def org_detail(request, org_id):
    """조직 현황. README §3."""
    org = org_or_404(request.user, org_id)
    request.session["org_id"] = org.pk
    include_archived = request.GET.get("include_archived") == "1"
    st = org_status(org)
    c = st["counts"]
    me_url = reverse("me")
    tiles = [
        ("미완료", c["open"], f"{me_url}?member=0", False),
        ("진행 중", c["doing"], f"{me_url}?member=0&status=doing", False),
        ("검토 대기", c["review"], f"{me_url}?member=0&status=review", False),
        ("기한 초과", c["overdue"], f"{me_url}?member=0&due=overdue", True),
        ("막힘", c["blocked"], f"{me_url}?member=0&status=blocked", True),
        ("완료", c["done"], f"{me_url}?member=0&status=done_7d", False),
    ]
    projects = org.projects.prefetch_related("owners", "teams").order_by("name")
    if not include_archived:
        projects = projects.filter(is_archived=False)
    return render(
        request,
        "orgs/detail.html",
        {
            "org": org,
            "tiles": tiles,
            "project_rows": [(p, project_stats(p)) for p in projects],
            "by_assignee": st["by_assignee"],
            "me_url": me_url,
            "include_archived": include_archived,
            "is_admin": can_admin(request.user, org),
            "tab": "overview",
        },
    )


def _admin_only(request, org_id):
    """조직 관리자 전용 화면의 공통 관문. 멤버에게는 화면 자체를 숨긴다(404)."""
    org = org_or_404(request.user, org_id)
    if not can_admin(request.user, org):
        raise Http404
    return org


@login_required
def org_teams(request, org_id):
    """조직 → 팀. 멤버·태그·초대·팀을 한 화면에서 관리한다."""
    org = _admin_only(request, org_id)
    load = {r["assignee_id"]: r for r in org_status(org)["by_assignee"]}
    rows = [
        {"m": m, "load": load.get(m.user_id)}
        for m in org.memberships.select_related("user").order_by("user__display_name")
    ]
    teams = [
        {
            "team": t,
            "member_count": t.members.count(),
            "project_count": t.projects.count(),
            "github": getattr(t, "github", None),
        }
        for t in org.teams.all()
    ]
    return render(
        request,
        "orgs/teams.html",
        {
            "org": org,
            "rows": rows,
            "admin_count": sum(1 for r in rows if r["m"].role == "admin"),
            "invites": org.invites.filter(revoked_at__isnull=True),
            "form": InviteForm(),
            "site_url": settings.SITE_URL,
            "team_rows": teams,
            "is_admin": True,
            "tab": "teams",
        },
    )


@login_required
@require_POST
def member_tags(request, membership_id):
    membership = get_object_or_404(OrgMembership.objects.select_related("org"), pk=membership_id)
    org_or_404(request.user, membership.org_id)
    tags = (request.POST.get("tags") or "").split(",")
    try:
        osv.set_tags(membership, tags, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.org_id)


def _member_redirect(request, org_id):
    return redirect("org_teams", org_id=org_id)


@login_required
@require_POST
def invite_create(request, org_id):
    org = org_or_404(request.user, org_id)
    form = InviteForm(request.POST)
    days = form.cleaned_data["days"] if form.is_valid() else 7
    try:
        invite = osv.create_invite(org, request.user, days=days)
        messages.success(request, f"초대 링크: {settings.SITE_URL}{invite.path}")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org.pk)
    if settings.GITHUB_ENABLED and form.is_valid() and form.cleaned_data["gh_invite"]:
        login = form.cleaned_data["gh_login"].strip()
        if login:
            warn = gh_writes.try_write(gh_writes.invite_to_org, org, login, actor=request.user)
            if warn:
                messages.warning(request, warn)
            else:
                messages.success(request, f"GitHub 조직에도 @{login}님을 초대했습니다.")
    return _member_redirect(request, org.pk)


@login_required
@require_POST
def invite_revoke(request, invite_id):
    invite = get_object_or_404(Invite.objects.select_related("org"), pk=invite_id)
    org_or_404(request.user, invite.org_id)
    try:
        osv.revoke_invite(invite, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, invite.org_id)


@login_required
@require_POST
def member_role(request, membership_id):
    membership = get_object_or_404(OrgMembership.objects.select_related("org"), pk=membership_id)
    org_or_404(request.user, membership.org_id)
    try:
        osv.change_role(membership, request.POST.get("role", ""), request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.org_id)


@login_required
@require_POST
def member_remove(request, membership_id):
    membership = get_object_or_404(
        OrgMembership.objects.select_related("org", "user"), pk=membership_id
    )
    org_or_404(request.user, membership.org_id)
    org_id = membership.org_id
    org, user = membership.org, membership.user
    try:
        osv.remove_member(membership, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org_id)
    if settings.GITHUB_ENABLED and getattr(org, "github", None) is not None:
        login = gh_writes._login_of(user)
        if login:
            warn = gh_writes.try_write(gh_writes.remove_from_org, org, login, actor=request.user)
            if warn:
                messages.warning(request, warn)
    return _member_redirect(request, org_id)


@login_required
def org_governance(request, org_id):
    """개발 거버넌스. 멤버는 읽고 관리자는 고친다."""
    org = org_or_404(request.user, org_id)
    is_admin = can_admin(request.user, org)
    error = ""
    if request.method == "POST" and is_admin:
        try:
            osv.set_governance(
                org, "" if request.POST.get("reset") else request.POST["text"], request.user
            )
            messages.success(request, "거버넌스를 저장했습니다.")
            return redirect("org_governance", org_id=org.pk)
        except ServiceError as e:
            error = "; ".join(e.errors.values())
    return render(
        request,
        "orgs/governance.html",
        {
            "org": org,
            "text": governance_text(org),
            "is_default": not org.governance.strip(),
            "is_admin": is_admin,
            "error": error,
            "tab": "governance",
        },
    )
