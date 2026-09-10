from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from accounts.services import (
    issue_link_code,
    link_discord,
    unlink_discord,
    user_by_discord_id,
)
from common.errors import ServiceError

pytestmark = pytest.mark.django_db


def test_display_name_truncated_from_long_username():
    """username 150자를 display_name(50자)에 그대로 복사하면 Postgres에서 DataError."""
    u = User.objects.create_user("a" * 120, password="pw12345678")
    assert len(u.display_name) == 50


# ---------- Discord 계정 연결 ----------


def _expire(user):
    User.objects.filter(pk=user.pk).update(
        discord_link_expires_at=timezone.now() - timedelta(seconds=1)
    )


def test_link_discord_fills_the_pair_and_clears_the_code(admin):
    """코드(웹 세션)와 snowflake(게이트웨이)가 만나야 연결된다. 코드는 재사용 불가로 비운다."""
    code = issue_link_code(admin)
    assert len(code) == 8 and code == code.upper()

    linked = link_discord(code, "222")
    assert linked.pk == admin.pk
    admin.refresh_from_db()
    assert admin.discord_user_id == "222"
    assert admin.discord_linked_at is not None
    # ""로 비우면 두 번째 사용자가 unique 제약에 걸린다. 반드시 None이어야 한다.
    assert admin.discord_link_code is None
    assert admin.discord_link_expires_at is None
    assert user_by_discord_id("222") == admin


def test_expired_code_changes_nothing(admin):
    code = issue_link_code(admin)
    _expire(admin)
    with pytest.raises(ServiceError):
        link_discord(code, "222")
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert admin.discord_linked_at is None
    assert admin.discord_link_code == code  # 실패는 코드를 태우지 않는다


def test_code_is_single_use(admin, outsider):
    code = issue_link_code(admin)
    link_discord(code, "222")
    with pytest.raises(ServiceError):
        link_discord(code, "333")
    outsider.refresh_from_db()
    assert outsider.discord_user_id is None
    assert user_by_discord_id("333") is None


def test_non_numeric_snowflake_rejected(admin):
    """snowflake는 10진 정수 문자열이다. 사람이 타이핑한 값이 들어오는 경로를 막는다."""
    code = issue_link_code(admin)
    for bad in ("", "  ", "abc", "<@222>", "222 333", "2.22"):
        with pytest.raises(ServiceError):
            link_discord(code, bad)
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert admin.discord_link_code == code


def test_link_takes_the_snowflake_from_the_previous_holder(admin, outsider):
    """코드와 snowflake가 둘 다 증명된 이 순간, 남의 행에 남아 있는 값이 틀린 것이다.

    선점당해 영구히 잠기는 경로가 없어야 admin을 readonly로 둘 수 있다.
    """
    User.objects.filter(pk=outsider.pk).update(
        discord_user_id="222", discord_linked_at=timezone.now()
    )
    link_discord(issue_link_code(admin), "222")

    outsider.refresh_from_db()
    admin.refresh_from_db()
    assert outsider.discord_user_id is None
    assert outsider.discord_linked_at is None
    assert admin.discord_user_id == "222"
    assert user_by_discord_id("222") == admin


def test_unlink_then_link_again(admin):
    link_discord(issue_link_code(admin), "222")
    unlink_discord(admin)
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert user_by_discord_id("222") is None

    link_discord(issue_link_code(admin), "222")
    assert user_by_discord_id("222") == admin


def test_user_by_discord_id_needs_a_proven_active_link(admin):
    """검증되지 않은 값과 비활성 계정은 명령 경로에 들어올 수 없다."""
    # 마이그레이션이 비우기 전의 손입력 값 같은 반쪽 행: 연결 시각이 없다.
    unproven = User.objects.create_user("typed", password="pw12345678", discord_user_id="444")
    assert unproven.discord_linked_at is None
    assert user_by_discord_id("444") is None

    link_discord(issue_link_code(admin), "222")
    User.objects.filter(pk=admin.pk).update(is_active=False)
    assert user_by_discord_id("222") is None
