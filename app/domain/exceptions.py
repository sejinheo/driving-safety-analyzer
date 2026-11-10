from abc import ABC
from typing import Any


class AppError(ABC, Exception):
    """모든 도메인 예외의 기반 클래스. 직접 인스턴스화하지 않는다."""

    code: str
    status_code: int
    message: str
    detail: dict[str, Any]

    def __init__(
        self,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class TripNotFoundError(AppError):
    """Trip이 존재하지 않거나 run이 COMPLETED가 아닌 경우."""

    code = "TRIP_NOT_FOUND"
    status_code = 404

    def __init__(self, trip_id: int) -> None:
        super().__init__(
            message=f"Trip {trip_id} not found",
            detail={"trip_id": trip_id},
        )


class EmptyLogFileError(AppError):
    """업로드한 파일이 비어 있는 경우."""

    code = "EMPTY_LOG_FILE"
    status_code = 400

    def __init__(self) -> None:
        super().__init__(message="Log file is empty")


class InvalidLogFormatError(AppError):
    """JSON 파싱 불가 또는 최상위가 배열이 아닌 경우."""

    code = "INVALID_LOG_FORMAT"
    status_code = 422

    def __init__(self, reason: str) -> None:
        super().__init__(message=f"Invalid log format: {reason}", detail={"reason": reason})


class DuplicateAnalysisError(AppError):
    """같은 파일이 이미 처리 중인 경우."""

    code = "DUPLICATE_ANALYSIS"
    status_code = 409

    def __init__(self, file_hash: str) -> None:
        super().__init__(
            message="Analysis already in progress for this file",
            detail={"file_hash": file_hash},
        )


class PayloadTooLargeError(AppError):
    """업로드 파일이 크기 제한을 초과한 경우."""

    code = "PAYLOAD_TOO_LARGE"
    status_code = 413

    def __init__(self, max_mb: int) -> None:
        super().__init__(
            message=f"File exceeds maximum allowed size of {max_mb}MB",
            detail={"max_mb": max_mb},
        )


class DbUnavailableError(AppError):
    """DB 연결 실패 또는 재시도 한도 초과."""

    code = "DB_UNAVAILABLE"
    status_code = 503

    def __init__(self) -> None:
        super().__init__(message="Database is unavailable")
