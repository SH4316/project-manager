import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _token():
    return secrets.token_urlsafe(32)


def _default_expiry():
    return timezone.now() + timedelta(days=7)


class Team(models.Model):
    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Membership", related_name="teams"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLES = [("admin", "관리자"), ("member", "팀원")]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=6, choices=ROLES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="membership_team_user"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.team} ({self.role})"


class Invite(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, default=_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    revoked_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    @property
    def path(self) -> str:
        return f"/join/{self.token}"


# Discord가 발급하는 Webhook URL 형태. 이 host로만 보내므로 임의 주소로 요청이 새지 않는다.
WEBHOOK_RE = re.compile(
    r"^https://(?:discord|discordapp)\.com/api/webhooks/\d{1,25}/[A-Za-z0-9_-]{1,200}$"
)


class DiscordWebhook(models.Model):
    """팀의 Discord 알림 채널.

    URL 뒷부분이 그 자체로 비밀이다(아는 사람은 누구나 그 채널에 글을 쓸 수 있다).
    화면·로그·백업에는 `masked`만 쓴다. 원문은 discord 서비스가 API로만 읽는다.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="webhooks")
    name = models.CharField("채널 이름", max_length=50)
    url = models.CharField("Webhook URL", max_length=300)
    is_active = models.BooleanField("사용", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_detail = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["team", "url"], name="webhook_team_url"),
        ]

    def __str__(self):
        return f"{self.name} @ {self.team}"

    @property
    def masked(self) -> str:
        """`…/webhooks/<채널 id>/••••••••뒤4자`. 두 웹훅을 구분할 만큼만 보여준다.

        짧은 토큰이면 뒤 네 자도 보여주지 않는다(그만큼이 전체의 큰 몫이 된다).
        """
        head, _, tail = self.url.rpartition("/")
        return f"{head}/{'•' * 8}{tail[-4:] if len(tail) > 12 else ''}"
