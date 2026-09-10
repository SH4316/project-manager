import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_display_name_truncated_from_long_username():
    """username 150자를 display_name(50자)에 그대로 복사하면 Postgres에서 DataError."""
    u = User.objects.create_user("a" * 120, password="pw12345678")
    assert len(u.display_name) == 50
