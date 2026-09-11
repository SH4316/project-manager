from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    return Fernet(settings.CREDENTIAL_KEY.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt((value or "").encode()).decode()


def decrypt(value: str) -> str:
    """복호화에 실패하면 빈 문자열. 키를 갈았을 때 로그인 자체가 막히지 않게 한다."""
    try:
        return _fernet().decrypt((value or "").encode()).decode()
    except (InvalidToken, ValueError):
        return ""
