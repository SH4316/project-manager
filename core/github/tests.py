"""GitHub 연동의 보안 경계 테스트.

여기 있는 것은 틀리면 조용히 뚫리는 자리다. 화면·규칙 테스트와 섞지 않는다.
"""

import hashlib
import hmac
import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone

from common.errors import ServiceError
from github import services as ghs
from github.conftest import signed
from github.crypto import decrypt, encrypt
from github.models import GitEvent, GitHubIdentity, GitHubInstallation, RepoConnection

pytestmark = pytest.mark.django_db


def _key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def conn(gh, project, admin):
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )


# ---------- 웹훅 인증 ----------


def test_webhook_rejects_bad_signature(gh, client, conn):
    body = json.dumps({"repository": {"full_name": "o/r"}}).encode()
    bad = "sha256=" + hmac.new(b"wrong", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/integrations/github/webhook",
        body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": bad, "X-GitHub-Event": "push", "X-GitHub-Delivery": "d"},
    )
    assert r.status_code == 401
    assert not GitEvent.objects.exists()


def test_webhook_rejects_missing_signature(gh, client, conn):
    r = client.post(
        "/api/integrations/github/webhook",
        json.dumps({"repository": {"full_name": "o/r"}}),
        content_type="application/json",
        headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "d"},
    )
    assert r.status_code == 401


def test_webhook_rejects_when_secret_unset(settings, client, conn):
    """비밀이 비어 있으면 전부 거부한다. 열어 두면 인증 없는 공개 쓰기 경로가 된다."""
    settings.GITHUB_WEBHOOK_SECRET = ""
    body = json.dumps({"repository": {"full_name": "o/r"}}).encode()
    sig = "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/integrations/github/webhook",
        body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "push", "X-GitHub-Delivery": "d"},
    )
    assert r.status_code == 401


def test_webhook_rejects_session_and_token(gh, client, admin, write_token, conn):
    """세션 쿠키도 API 토큰도 이 경로에 들어오지 못한다."""
    client.force_login(admin)
    payload = json.dumps({"repository": {"full_name": "o/r"}})
    r = client.post("/api/integrations/github/webhook", payload, content_type="application/json")
    assert r.status_code == 401
    r = client.post(
        "/api/integrations/github/webhook",
        payload,
        content_type="application/json",
        headers={"Authorization": f"Bearer {write_token[1]}"},
    )
    assert r.status_code == 401


def test_webhook_accepts_good_signature(gh, client, conn):
    r = signed(client, {"repository": {"full_name": "o/r"}}, "membership", "d-ok")
    assert r.status_code == 202


def test_webhook_ignores_unconnected_repo(gh, client):
    r = signed(client, {"repository": {"full_name": "other/repo"}}, "push", "d-x")
    assert r.status_code == 202
    assert not GitEvent.objects.exists()


def test_webhook_not_throttled(gh, client, conn):
    """전역 분당 60건 한도에 웹훅이 묶이면 push가 몰릴 때 429가 난다."""
    codes = {
        signed(client, {"repository": {"full_name": "o/r"}}, "membership", f"t-{i}").status_code
        for i in range(70)
    }
    assert 429 not in codes


# ---------- 토큰 ----------


def test_encrypt_roundtrip_and_bad_key(gh):
    token = encrypt("ghu_secret")
    assert decrypt(token) == "ghu_secret"
    # 키를 갈면 옛 토큰은 못 읽는다. 예외가 아니라 빈 문자열이어야 로그인이 막히지 않는다.
    gh.CREDENTIAL_KEY = Fernet.generate_key().decode()
    assert decrypt(token) == ""
    assert decrypt("not-a-token") == ""


def test_user_token_refreshes_when_expired(gh, admin, monkeypatch):
    identity = GitHubIdentity.objects.create(user=admin, github_id=1, login="a")
    gh_store(identity, "old", "refresh-me", expired=True)
    called = {}

    def fake_refresh(token):
        called["token"] = token
        return {"access_token": "new-token", "expires_in": 28800}

    monkeypatch.setattr("github.client.refresh_user_token", fake_refresh)
    assert gh_token(identity) == "new-token"
    assert called["token"] == "refresh-me"


def test_user_token_raises_when_refresh_dead(gh, admin):
    identity = GitHubIdentity.objects.create(user=admin, github_id=2, login="b")
    gh_store(identity, "old", "", expired=True)
    with pytest.raises(ServiceError):
        gh_token(identity)


def gh_store(identity, access, refresh, *, expired=False):
    identity.token_enc = encrypt(access)
    identity.refresh_enc = encrypt(refresh) if refresh else ""
    identity.token_expires_at = timezone.now() - timedelta(minutes=5 if expired else -60)
    identity.refresh_expires_at = timezone.now() + timedelta(days=30)
    identity.save()
    return None


def gh_token(identity):
    return ghs.user_token(identity)


def test_app_jwt_is_rs256_and_signed(gh):
    """PyJWT 없이 만든 JWT가 실제로 RS256 서명인지 공개키로 확인한다."""
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = _key_pem()
    gh.GITHUB_APP_PRIVATE_KEY = pem
    token = gh_app_jwt()
    header_b64, payload_b64, sig_b64 = token.split(".")

    def unb64(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    assert json.loads(unb64(header_b64))["alg"] == "RS256"
    assert json.loads(unb64(payload_b64))["iss"] == "1"
    private = serialization.load_pem_private_key(pem.encode(), password=None)
    private.public_key().verify(
        unb64(sig_b64),
        f"{header_b64}.{payload_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def gh_app_jwt():
    from github.client import app_jwt

    return app_jwt()


# ---------- 권한 필터 ----------


def test_repo_state_four_cases(gh, project, admin, member, conn):
    from github.services import repo_state

    project.repo = conn
    # 저장소는 있는데 GitHub 미연결
    assert repo_state(member, project)["state"] == "unlinked"
    # 연결은 했지만 그 저장소가 목록에 없다
    GitHubIdentity.objects.create(user=member, github_id=9, login="m", repos=["other/repo"])
    member.refresh_from_db()
    assert repo_state(member, project)["state"] == "denied"
    # 목록에 있으면 ok
    member.github.repos = ["o/r"]
    member.github.save()
    assert repo_state(member, project)["state"] == "ok"
    # 저장소 연결 자체가 없으면 none
    conn.delete()
    project.refresh_from_db()
    assert repo_state(member, project)["state"] == "none"


def test_can_view_repo_needs_identity(gh, member):
    from github.services import can_view_repo

    assert can_view_repo(member, "o/r") is False
    assert can_view_repo(member, "") is False


def test_connect_repo_requires_access(gh, project, member, org):
    """볼 수 없는 저장소는 연결할 수 없다."""
    # 저장소 연결은 프로젝트 관리자 등급이다 — 여기서 보는 건 GitHub 접근 쪽이다
    project.owners.add(member)
    with pytest.raises(ServiceError):
        ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=member)
    GitHubIdentity.objects.create(user=member, github_id=5, login="m", repos=["o/r"])
    member.refresh_from_db()
    conn = ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=member)
    assert conn.full_name == "o/r"


def test_connect_repo_requires_membership(gh, project, outsider):
    GitHubIdentity.objects.create(user=outsider, github_id=6, login="o", repos=["o/r"])
    outsider.refresh_from_db()
    with pytest.raises(ServiceError):
        ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=outsider)


def test_connect_repo_settings_by_admin_blocks_project_owner(gh, org, admin, member, project):
    """저장소 연결은 project.settings_by 등급을 탄다 — admin으로 잠그면 프로젝트 관리자도 막힌다."""
    project.owners.set([member])
    GitHubIdentity.objects.create(user=member, github_id=7, login="m", repos=["o/r"])
    GitHubIdentity.objects.create(user=admin, github_id=17, login="ad", repos=["o/r"])
    member.refresh_from_db()
    admin.refresh_from_db()
    org.settings = {"project.settings_by": "admin"}
    org.save(update_fields=["settings"])
    with pytest.raises(ServiceError):
        ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=member)
    conn = ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=admin)
    assert conn.full_name == "o/r"


def test_connect_repo_ai_gate(gh, org, admin, project):
    """source=mcp일 때만 ai.manage_repo를 본다. web 경로는 그대로 통과한다."""
    GitHubIdentity.objects.create(user=admin, github_id=8, login="a", repos=["o/r"])
    admin.refresh_from_db()
    org.settings = {"ai.manage_repo": "deny"}
    org.save(update_fields=["settings"])
    with pytest.raises(ServiceError):
        ghs.connect_repo(
            project=project, url="https://github.com/o/r.git", actor=admin, source="mcp"
        )
    conn = ghs.connect_repo(
        project=project, url="https://github.com/o/r.git", actor=admin, source="web"
    )
    assert conn.full_name == "o/r"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "git@github.com:owner/repo.git",
        "https://github.com/owner/repo/",
    ],
)
def test_parse_repo_url_variants(url):
    assert ghs.parse_repo_url(url) == "owner/repo"


def test_parse_repo_url_rejects_other_hosts():
    with pytest.raises(ServiceError):
        ghs.parse_repo_url("https://gitlab.com/owner/repo.git")


def test_sync_repos_only_own_orgs(gh, admin, org, monkeypatch, member):
    """다른 조직의 설치는 묻지 않는다."""
    from orgs.services import create_org

    other = create_org("남의 조직", "", member)
    GitHubInstallation.objects.create(
        org=org, installation_id=11, account_login="mine", installed_by=admin
    )
    GitHubInstallation.objects.create(
        org=other, installation_id=22, account_login="theirs", installed_by=member
    )
    identity = GitHubIdentity.objects.create(user=admin, github_id=3, login="a")
    gh_store(identity, "tok", "ref")
    asked = []

    def fake_request(method, path, token, **kw):
        asked.append(path)
        return {"repositories": [{"full_name": "mine/repo"}]}

    monkeypatch.setattr("github.client.request", fake_request)
    repos = ghs.sync_repos(identity)
    assert repos == ["mine/repo"]
    assert any("/11/" in p for p in asked)
    assert not any("/22/" in p for p in asked)


# ---------- actor=None 경계 ----------


def test_actor_none_only_from_github_services():
    """actor=None을 tasks.services에 넘기는 코드가 github/ 밖에 없다."""
    root = Path(__file__).resolve().parent.parent
    hits = subprocess.run(
        ["git", "grep", "-n", "actor=None", "--", "*.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # Windows 기본 코덱(cp949)이 한글 줄에서 터진다
    ).stdout.splitlines()
    outside = [
        h
        for h in hits
        if not h.startswith("github/") and "tests.py" not in h and "/tests/" not in h
    ]
    assert outside == [], outside
