from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from projects.models import Project
from projects.services import create_project, update_project
from teams.services import teams_of

from ..context import ctx, team_or_404
from ..schemas import ConflictOut, ErrorOut, ProjectCreateIn, ProjectOut, ProjectPatchIn
from ..serialize import project_out

router = Router(tags=["projects"])


def _visible(request):
    return (
        Project.objects.filter(team__in=teams_of(request.auth))
        .select_related("team")
        .prefetch_related("owners")
    )


def _project_or_404(request, project_id: int) -> Project:
    p = _visible(request).filter(pk=project_id).first()
    if p is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    return p


def _owners(ids: list[int]) -> list[User]:
    users = list(User.objects.filter(pk__in=ids))
    if len(users) != len(set(ids)):
        raise HttpError(400, "관리자를 찾을 수 없습니다.")
    return users


@router.get("", response=list[ProjectOut])
def list_projects(request, team: int | None = None, include_archived: bool = False):
    qs = _visible(request)
    if team is not None:
        qs = qs.filter(team_id=team)
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return [project_out(p) for p in qs.order_by("team__name", "name")]


@router.get("/{project_id}", response=ProjectOut)
def get_project(request, project_id: int):
    return project_out(_project_or_404(request, project_id))


@router.post("", response={201: ProjectOut, 400: ErrorOut})
def create_project_ep(request, payload: ProjectCreateIn):
    team = team_or_404(request, payload.team_id)
    p = create_project(
        team=team,
        name=payload.name,
        purpose=payload.purpose,
        owners=_owners(payload.owner_ids),
        status=payload.status,
        **ctx(request),
    )
    return 201, project_out(p)


@router.patch("/{project_id}", response={200: ProjectOut, 400: ErrorOut, 409: ConflictOut})
def patch_project(request, project_id: int, payload: ProjectPatchIn):
    p = _project_or_404(request, project_id)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    if "owner_ids" in data:
        data["owners"] = _owners(data.pop("owner_ids") or [])
    p = update_project(p, data, expected_version=version, **ctx(request))
    return project_out(p)
