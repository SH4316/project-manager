class ServiceError(Exception):
    """검증 실패. errors는 {필드명: 메시지}."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(str(errors))


class ConflictError(Exception):
    """낙관적 잠금 충돌. latest는 DB의 최신 객체."""

    def __init__(self, latest):
        self.latest = latest
        super().__init__("conflict")
