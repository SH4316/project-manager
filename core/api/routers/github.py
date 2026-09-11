"""GitHub 웹훅 수신. 이 경로의 인증은 서명 하나뿐이다."""

import hashlib
import hmac
import json

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from ninja import Router

from github import services as gh_services


class WebhookAuth:
    """X-Hub-Signature-256만 믿는다. 세션 쿠키도 API 토큰도 이 경로에 들어오지 못한다.

    비밀이 비어 있으면 전부 거부한다 — 비어 있는 채로 열어 두면 주소를 아는 누구나
    아무 이벤트나 밀어 넣어 태스크 상태를 바꿀 수 있다.
    """

    def __call__(self, request):
        secret = settings.GITHUB_WEBHOOK_SECRET.encode()
        if not secret:
            return None
        sent = request.headers.get("X-Hub-Signature-256", "")
        mine = "sha256=" + hmac.new(secret, request.body, hashlib.sha256).hexdigest()
        # compare_digest를 쓴다. == 비교는 길이와 내용에 따라 시간이 달라진다.
        if not hmac.compare_digest(sent, mine):
            return None
        return AnonymousUser()


# throttle=[]: 전역 UserRateThrottle은 request.auth.pk가 없으면 문자열 키 하나로 묶어
# 모든 웹훅을 분당 60건 공용 한도에 넣는다. push가 몰리면 429가 난다.
router = Router(tags=["github"], auth=WebhookAuth(), throttle=[])


@router.post("/webhook", response={200: dict, 202: dict})
def webhook(request):
    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "")
    payload = json.loads(request.body or b"{}")
    return gh_services.handle_event(event, delivery, payload)
