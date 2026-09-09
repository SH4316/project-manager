from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from tasks import services as ts

from .common import rows_for


@login_required
def search(request):
    q = request.GET.get("q", "")
    include_closed = request.GET.get("include_closed") == "1"
    include_archived = request.GET.get("include_archived") == "1"
    results = list(
        ts.search(request.user, q, include_closed=include_closed, include_archived=include_archived)
    )
    return render(
        request,
        "search.html",
        {
            "q": q,
            "count": len(results),
            "rows": rows_for(request.user, results),
            "include_closed": include_closed,
            "include_archived": include_archived,
        },
    )
