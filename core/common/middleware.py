def origin_agent_cluster(get_response):
    """WebMCP는 오리진 키 에이전트 클러스터에서만 동작한다.

    스펙상 `document.modelContext`의 registerTool·getTools·executeTool은 문서가 오리진 키가
    아니면 SecurityError로 거절한다. 브라우저가 기본으로 오리진 키를 주는지는 보장이 없으므로
    헤더로 못 박는다. 이 사이트는 document.domain을 쓰지 않아 잃는 것이 없다.
    """

    def middleware(request):
        response = get_response(request)
        response.headers.setdefault("Origin-Agent-Cluster", "?1")
        return response

    return middleware
