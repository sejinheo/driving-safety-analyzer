from enum import StrEnum


class RunStatus(StrEnum):
    """분석 run의 상태."""

    PENDING = "PENDING"
    INGESTING = "INGESTING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EventType(StrEnum):
    """위험 운전 이벤트 유형."""

    HARSH_ACCEL = "HARSH_ACCEL"
    HARSH_DECEL = "HARSH_DECEL"
    SCHOOL_ZONE_SPEEDING = "SCHOOL_ZONE_SPEEDING"
