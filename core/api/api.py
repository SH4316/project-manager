from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI
from ninja.security import django_auth
from ninja.throttling import AuthRateThrottle

from common.errors import ConflictError, ServiceError

from .auth import TokenAuth
from .routers import integrations, me, projects, reports, tasks, teams, today
from .serialize import project_out, task_out

api = NinjaAPI(
    title="Sandol PM API",
    version="1",
    auth=[django_auth, TokenAuth()],
    throttle=[AuthRateThrottle("60/m")],
    docs_decorator=login_required,
    urls_namespace="api",
)


@api.exception_handler(ServiceError)
def _service_error(request, exc):
    return api.create_response(request, {"detail": exc.errors}, status=400)


@api.exception_handler(ConflictError)
def _conflict(request, exc):
    latest = exc.latest
    data = task_out(latest) if hasattr(latest, "assignee") else project_out(latest)
    return api.create_response(request, {"detail": "conflict", "latest": data}, status=409)


api.add_router("/", me.router)
api.add_router("/teams", teams.router)
api.add_router("/projects", projects.router)
api.add_router("/tasks", tasks.router)
api.add_router("/today", today.router)
api.add_router("/reports", reports.router)
api.add_router("/integrations", integrations.router)
